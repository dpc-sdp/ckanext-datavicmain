from __future__ import annotations

import logging
from typing import Any, cast, Union

from flask import Blueprint, Response
from flask.views import MethodView

import ckan.plugins as plugins
import ckan.types as types
import ckan.plugins.toolkit as tk
import ckan.logic as logic
import ckan.model as model
import ckan.lib.authenticator as authenticator
import ckan.lib.captcha as captcha
import ckan.views.user as user
import ckan.lib.navl.dictization_functions as dictization_functions
from ckan import authz
from ckan.lib import signals

from ckanext.mailcraft.utils import get_mailer
from ckanext.mailcraft.exception import MailerException

import ckanext.datavicmain.helpers as helpers
import ckanext.datavicmain.utils as utils

log = logging.getLogger(__name__)

datavicuser = Blueprint("datavicuser", __name__)
mailer = get_mailer()


class DataVicRequestResetView(user.RequestResetView):
    def _prepare(self):
        return super()._prepare()

    def get(self):
        self._prepare()
        return tk.render("user/request_reset.html", {})

    def post(self):
        """
        POST method datavic user
        """
        self._prepare()

        user_id = tk.request.form.get("user")

        if user_id in (None, ""):
            tk.h.flash_error(tk._("Email is required"))
            return tk.h.redirect_to("/user/reset")

        context = cast(
            types.Context,
            {
                "model": model,
                "user": tk.current_user.name,
                "ignore_auth": True,
            },
        )
        user_objs = []

        if "@" not in user_id:
            try:
                user_dict = tk.get_action("user_show")(
                    context, {"id": user_id}
                )
                user_objs.append(context["user_obj"])
            except tk.ObjectNotFound:
                pass
        else:
            user_list = tk.get_action("user_list")(context, {"email": user_id})
            if user_list:
                # send reset emails for *all* user accounts with this email
                # (otherwise we'd have to silently fail - we can't tell the
                # user, as that would reveal the existence of accounts with
                # this email address)
                for user_dict in user_list:
                    tk.get_action("user_show")(
                        context, {"id": user_dict["id"]}
                    )
                    user_objs.append(context["user_obj"])

        if not user_objs:
            log.info(
                "User requested reset link for unknown user: {}".format(
                    user_id
                )
            )

        for user_obj in user_objs:
            log.info("Emailing reset link to user: {}".format(user_obj.name))
            try:
                # DATAVIC-221: Do not create/send reset link if user was self-registered and currently pending
                if user_obj.is_pending() and not user_obj.reset_key:
                    tk.h.flash_error(
                        tk._(
                            "Unable to send reset link - please contact the site administrator."
                        )
                    )
                    return tk.h.redirect_to("/user/reset")
                else:
                    mailer.send_reset_link(user_obj)
            except MailerException as e:
                tk.h.flash_error(
                    tk._(
                        "Error sending the email. Try again later "
                        "or contact an administrator for help"
                    )
                )
                log.exception(e)
                return tk.h.redirect_to("/")
        # always tell the user it succeeded, because otherwise we reveal
        # which accounts exist or not
        tk.h.flash_success(
            tk._(
                "A reset link has been emailed to you "
                "(unless the account specified does not exist)"
            )
        )
        return tk.h.redirect_to("/")


class DataVicPerformResetView(user.PerformResetView):
    def _prepare(self, id) -> tuple[types.Context, dict[str, Any]]:
        return super()._prepare(id)

    def get(self, user_id: str) -> Union[Response, str]:
        # FIXME 403 error for invalid key is a non helpful page
        context = cast(
            types.Context,
            {
                "model": model,
                "session": model.Session,
                "user": user_id,
                "keep_email": True,
            },
        )

        try:
            tk.check_access("user_reset", context)
        except tk.NotAuthorized as e:
            log.debug(str(e))
            tk.abort(403, tk._("Unauthorized to reset password."))

        try:
            user_dict = tk.get_action("user_show")(context, {"id": user_id})
            user_obj = context["user_obj"]
        except tk.ObjectNotFound:
            tk.abort(404, tk._("User not found"))

        tk.g.reset_key = tk.request.args.get("key")

        if not mailer.verify_reset_link(user_obj, tk.g.reset_key):
            tk.h.flash_error(tk._("Invalid reset key. Please try again."))
            tk.abort(403)

        return tk.render("user/perform_reset.html", {"user_dict": user_dict})

    def post(self, user_id: str):
        context, user_dict = self._prepare(user_id)
        context["reset_password"] = True
        user_state = user_dict["state"]

        try:
            # If you only want to automatically login new users,
            # check that user_dict['state'] == 'pending'
            new_password = super()._get_form_password()
            user_dict["password"] = new_password
            user_dict["reset_key"] = tk.g.reset_key
            user_dict["state"] = model.State.ACTIVE

            username = tk.request.form.get("name")

            if username is not None and username != "":
                user_dict["name"] = username

            updated_user = tk.get_action("user_update")(context, user_dict)

            # Users can not change their own state, so we need another edit
            if updated_user["state"] == model.State.PENDING:
                patch_context = cast(
                    types.Context,
                    {
                        "user": tk.get_action("get_site_user")(
                            {"ignore_auth": True}, {}
                        )["name"]
                    },
                )
                tk.get_action("user_patch")(
                    patch_context,
                    {"id": user_dict["id"], "state": model.State.ACTIVE},
                )

            mailer.create_reset_key(context["user_obj"])
            signals.perform_password_reset.send(
                username, user=context["user_obj"]
            )

            tk.h.flash_success(tk._("Your password has been reset."))

            if not tk.g.user:
                # log the user in programmatically
                user.set_repoze_user(user_dict["name"])
                return tk.h.redirect_to("datavicuser.me")

            # DataVic customization
            # Redirect to different pages depending on user access
            if tk.h.check_access("package_create"):
                return tk.h.redirect_to("user.read", id=updated_user["name"])
            else:
                return tk.h.redirect_to(
                    "activity.user_activity", id=updated_user["name"]
                )
        except tk.NotAuthorized:
            tk.h.flash_error(tk._("Unauthorized to edit user %s") % user_id)
        except tk.ObjectNotFound:
            tk.h.flash_error(tk._("User not found"))
        except dictization_functions.DataError:
            tk.h.flash_error(tk._("Integrity Error"))
        except tk.ValidationError as e:
            tk.h.flash_error("%r" % e.error_dict)
        except ValueError as e:
            tk.h.flash_error(str(e))

        user_dict["state"] = user_state
        return tk.render("user/perform_reset.html", {"user_dict": user_dict})


class DataVicUserEditView(user.EditView):
    def _prepare(self, id):
        return super()._prepare(id)

    def post(self, id=None):
        context, id = self._prepare(id)

        if not context["save"]:
            return self.get(id)

        current_user = id in (
            ("" if tk.current_user.is_anonymous else tk.current_user.id),
            tk.current_user.name,
        )
        old_username = tk.current_user.name

        try:
            data_dict = logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(tk.request.form))
                )
            )
            data_dict.update(
                logic.clean_dict(
                    dictization_functions.unflatten(
                        logic.tuplize_dict(
                            logic.parse_params(tk.request.files)
                        )
                    )
                )
            )

        except dictization_functions.DataError:
            tk.abort(400, tk._("Integrity Error"))
        data_dict.setdefault("activity_streams_email_notifications", False)

        context["message"] = data_dict.get("log_message", "")
        data_dict["id"] = id
        email_changed = data_dict["email"] != tk.current_user.email

        if (
            data_dict["password1"] and data_dict["password2"]
        ) or email_changed:

            # CUSTOM CODE to allow updating user pass for sysadmin without a sys pass
            self_update = data_dict["name"] == tk.current_user.name
            is_sysadmin = False if tk.current_user.is_anonymous else tk.current_user.sysadmin  # type: ignore

            if not is_sysadmin or self_update:
                identity = {
                    "login": tk.current_user.name,
                    "password": data_dict["old_password"],
                }
                auth_user = authenticator.ckan_authenticator(identity)
                auth_username = auth_user.name if auth_user else ""

                if auth_username != tk.current_user.name:
                    errors = {
                        "oldpassword": [tk._("Password entered was incorrect")]
                    }
                    error_summary = {
                        tk._("Old Password"): tk._("incorrect password")
                    }
                    return self.get(id, data_dict, errors, error_summary)

        try:
            updated_user = tk.get_action("user_update")(context, data_dict)
        except tk.NotAuthorized:
            tk.abort(403, tk._("Unauthorized to edit user %s") % id)
        except tk.ObjectNotFound:
            tk.abort(404, tk._("User not found"))
        except tk.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(id, data_dict, errors, error_summary)

        tk.h.flash_success(tk._("Profile updated"))
        resp = tk.h.redirect_to("user.read", id=updated_user["name"])
        if current_user and data_dict["name"] != old_username:
            # Changing currently logged in user's name.
            # Update repoze.who cookie to match
            user.set_repoze_user(data_dict["name"], resp)
        return resp

    def get(self, id=None, data=None, errors=None, error_summary=None):
        context, id = self._prepare(id)
        data_dict = {"id": id}
        is_myself = id in (
            (
                ""
                if tk.current_user.is_anonymous
                else tk.current_user.id
            ),
            tk.current_user.name,
        )

        is_sysadmin = tk.current_user.sysadmin

        if not any([is_sysadmin, is_myself]):
            return tk.abort(403, tk._("Not authorized to see this page."))

        try:
            old_data = tk.get_action("user_show")(context, data_dict)

            tk.g.display_name = old_data.get("display_name")
            tk.g.user_name = old_data.get("name")

            data = data or old_data

        except tk.NotAuthorized:
            tk.abort(403, tk._("Unauthorized to edit user %s") % "")
        except tk.ObjectNotFound:
            tk.abort(404, tk._("User not found"))

        errors = errors or {}
        vars = {"data": data, "errors": errors, "error_summary": error_summary}

        extra_vars = user._extra_template_variables(
            {"model": model, "session": model.Session, "user": tk.g.user},
            data_dict,
        )

        extra_vars["show_email_notifications"] = tk.asbool(
            tk.config.get("ckan.activity_streams_email_notifications")
        )
        vars.update(extra_vars)
        extra_vars["form"] = tk.render(user.edit_user_form, extra_vars=vars)

        return tk.render("user/edit.html", extra_vars)


def logged_in():
    # redirect if needed
    came_from = tk.request.args.get("came_from", "")

    if tk.h.url_is_local(came_from):
        return tk.h.redirect_to(str(came_from))

    if tk.g.user:
        return me()
    else:
        log.info("Login failed. Bad username or password.")
        return user.login()


def me():
    return (
        tk.h.redirect_to(
            tk.config.get("ckan.auth.route_after_login")
            or "dashboard.datasets"
        )
        if tk.h.check_access("package_create")
        else tk.h.redirect_to("dataset.search")
    )


def approve(user_id: str):
    try:
        data_dict = {"id": user_id}

        # Only sysadmins can activate a pending user
        tk.check_access("sysadmin", {})

        old_data = tk.get_action("user_show")({}, data_dict)
        username = old_data["name"]

        old_data["state"] = model.State.ACTIVE
        user = tk.get_action("user_update")({"ignore_auth": True}, old_data)

        # Send new account approved email to user
        tk.h.datavic_send_email(
            [user.get("email", "")],
            "new_account_approved",
            {
                "user_name": user.get("name", ""),
                "login_url": tk.url_for("user.login", qualified=True),
                "site_title": tk.config.get("ckan.site_title"),
                "site_url": tk.config.get("ckan.site_url"),
            },
        )

        tk.h.flash_success(tk._("User approved"))

        if data := utils.UserPendingEditorFlake.get_pending_user(user["id"]):
            utils.store_user_org_join_request(
                {
                    "name": data["name"],
                    "email": data["email"],
                    "organisation_id": data["organisation_id"],
                    "organisation_role": "editor",
                }
            )
            utils.UserPendingEditorFlake.remove_pending_user(user["id"])

        return tk.h.redirect_to("user.read", id=user["name"])
    except tk.NotAuthorized:
        tk.abort(403, tk._("Unauthorized to activate user."))
    except tk.ObjectNotFound as e:
        tk.abort(404, tk._("User not found"))
    except dictization_functions.DataError:
        tk.abort(400, tk._("Integrity Error"))
    except tk.ValidationError as e:
        for field, summary in e.error_summary.items():
            tk.h.flash_error(f"{field}: {summary}")

    return tk.h.redirect_to("user.read", id=username)


def deny(id):
    try:
        data_dict = {"id": id}

        # Only sysadmins can activate a pending user
        tk.check_access("sysadmin", {})

        user = tk.get_action("user_show")({}, data_dict)
        # Delete denied user
        tk.get_action("user_delete")({}, data_dict)

        # Send account requested denied email
        tk.h.datavic_send_email(
            [user.get("email", "")],
            "new_account_denied",
            {
                "user_name": user.get("name", ""),
                "site_title": tk.config.get("ckan.site_title"),
                "site_url": tk.config.get("ckan.site_url"),
            },
        )

        tk.h.flash_success(tk._("User Denied"))

        if utils.UserPendingEditorFlake.get_pending_user(user["id"]):
            utils.UserPendingEditorFlake.remove_pending_user(user["id"])

        return tk.h.redirect_to("user.read", id=user["name"])
    except tk.NotAuthorized:
        tk.abort(403, tk._("Unauthorized to reject user."))
    except tk.ObjectNotFound as e:
        tk.abort(404, tk._("User not found"))
    except dictization_functions.DataError:
        tk.abort(400, tk._("Integrity Error"))
    except tk.ValidationError as e:
        tk.h.flash_error("%r" % e.error_dict)


class RegisterView(MethodView):
    """
    This is copied from ckan_core views/user
    There is only 1 small change at the end which is to not login in registering users
    and redirect the user to the home page
    """

    def _prepare(self) -> types.Context:
        context = cast(
            types.Context,
            {
                "model": model,
                "session": model.Session,
                "user": tk.g.user,
                "auth_user_obj": tk.g.userobj,
                "schema": user._new_form_to_db_schema(),
                "save": "save" in tk.request.form,
            },
        )

        try:
            tk.check_access("user_create", context)
        except tk.NotAuthorized:
            tk.abort(403, tk._("Unauthorized to register as a user."))

        return context

    def post(self):
        context = self._prepare()
        try:
            data_dict = logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(tk.request.form))
                )
            )
            data_dict.update(
                logic.clean_dict(
                    dictization_functions.unflatten(
                        logic.tuplize_dict(
                            logic.parse_params(tk.request.files)
                        )
                    )
                )
            )

        except dictization_functions.DataError:
            tk.abort(400, tk._("Integrity Error"))

        context["message"] = data_dict.get("log_message", "")
        try:
            captcha.check_recaptcha(tk.request)
        except captcha.CaptchaError:
            error_msg = tk._("Bad Captcha. Please try again.")
            tk.h.flash_error(error_msg)
            return self.get(data_dict)

        try:
            tk.get_action("user_create")(context, data_dict)
        except tk.NotAuthorized:
            tk.abort(403, tk._("Unauthorized to create user %s") % "")
        except tk.ObjectNotFound:
            tk.abort(404, tk._("User not found"))
        except tk.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(data_dict, errors, error_summary)

        if tk.g.user:
            # #1799 User has managed to register whilst logged in - warn user
            # they are not re-logged in as new user.
            tk.h.flash_success(
                tk._(
                    'User "%s" is now registered but you are still '
                    'logged in as "%s" from before'
                )
                % (data_dict["name"], tk.g.user)
            )
            if authz.is_sysadmin(tk.g.user):
                # the sysadmin created a new user. We redirect him to the
                # activity page for the newly created user
                return tk.h.redirect_to(
                    "activity.user_activity", id=data_dict["name"]
                )
            else:
                return tk.render("user/logout_first.html")

        # DATAVIC custom updates
        if helpers.user_is_registering():
            # If user is registering, do not login them and redirect them to the home page
            tk.h.flash_success(
                tk._("Your requested account has been submitted for review")
            )
            resp = tk.h.redirect_to("home.index")
        else:
            # log the user in programmatically
            resp = tk.h.redirect_to("user.me")
            user.set_repoze_user(data_dict["name"], resp)
        return resp

    def get(self, data=None, errors=None, error_summary=None):
        self._prepare()

        if tk.g.user and not data and not authz.is_sysadmin(tk.g.user):
            # #1799 Don't offer the registration form if already logged in
            return tk.render("user/logout_first.html", {})

        form_vars = {
            "data": data or {},
            "errors": errors or {},
            "error_summary": error_summary or {},
        }

        extra_vars = {
            "is_sysadmin": authz.is_sysadmin(tk.g.user),
            "form": tk.render(user.new_user_form, form_vars),
        }
        return tk.render("user/new.html", extra_vars)


@datavicuser.before_request
def before_request() -> None:
    _, action = tk.get_endpoint()

    # Skip recaptcha check if 2FA is enabled, it will be checked with ckanext-auth
    if plugins.plugin_loaded("auth") and tk.h.is_2fa_enabled():
        return;

    if (
        tk.request.method == "POST"
        and action in ["login", "register", "request_reset"]
        and not tk.config.get("debug")
    ):
        try:
            captcha.check_recaptcha(tk.request)
        except captcha.CaptchaError:
            tk.h.flash_error(tk._(u'Bad Captcha. Please try again.'))
            return tk.h.redirect_to(tk.request.url)


def register_datavicuser_plugin_rules(blueprint):
    _edit_view = DataVicUserEditView.as_view(str("edit"))

    blueprint.add_url_rule(
        "/user/reset",
        view_func=DataVicRequestResetView.as_view(str("request_reset")),
    )
    blueprint.add_url_rule(
        "/user/reset/<user_id>",
        view_func=DataVicPerformResetView.as_view(str("perform_reset")),
    )
    blueprint.add_url_rule("/edit", view_func=_edit_view)
    blueprint.add_url_rule("/edit/<id>", view_func=_edit_view)
    blueprint.add_url_rule("/user/activate/<user_id>", view_func=approve)
    blueprint.add_url_rule("/user/deny/<id>", view_func=deny)
    blueprint.add_url_rule("/user/logged_in", view_func=logged_in)
    blueprint.add_url_rule("/user/me", view_func=me)
    blueprint.add_url_rule(
        "/user/register", view_func=RegisterView.as_view(str("register"))
    )
    blueprint.add_url_rule("/user/login", view_func=user.login, methods=("GET", "POST"))


register_datavicuser_plugin_rules(datavicuser)
