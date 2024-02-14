import logging
import six
import ckan.plugins.toolkit as toolkit
import ckan.logic as logic
import ckan.model as model
import ckan.lib.authenticator as authenticator
import ckan.lib.captcha as captcha
import ckan.views.user as user
import ckan.lib.navl.dictization_functions as dictization_functions

import ckanext.datavicmain.helpers as helpers


from flask import Blueprint
from flask.views import MethodView
from ckan.common import _, g, request
from ckan import authz

from ckanext.mailcraft.utils import get_mailer
from ckanext.mailcraft.exception import MailerException

NotFound = toolkit.ObjectNotFound
NotAuthorized = toolkit.NotAuthorized
ValidationError = toolkit.ValidationError
check_access = toolkit.check_access
get_action = toolkit.get_action
asbool = toolkit.asbool
h = toolkit.h
render = toolkit.render
abort = toolkit.abort
config = toolkit.config

DataError = dictization_functions.DataError
unflatten = dictization_functions.unflatten

tuplize_dict = logic.tuplize_dict
parse_params = logic.parse_params
clean_dict = logic.clean_dict

_extra_template_variables = user._extra_template_variables
edit_user_form = user.edit_user_form
set_repoze_user = user.set_repoze_user
_new_form_to_db_schema = user._new_form_to_db_schema
_new_user_form = user.new_user_form

log = logging.getLogger(__name__)

datavicuser = Blueprint('datavicuser', __name__)
mailer = get_mailer()

class DataVicRequestResetView(user.RequestResetView):
    def _prepare(self):
        return super()._prepare()

    def get(self):
        self._prepare()
        return render("user/request_reset.html", {})

    def post(self):
        """
        POST method datavic user
        """
        self._prepare()
        id = request.form.get("user")
        if id in (None, ""):
            h.flash_error(_("Email is required"))
            return h.redirect_to("/user/reset")
        context = {"model": model, "user": g.user, "ignore_auth": True}
        user_objs = []

        if "@" not in id:
            try:
                user_dict = get_action("user_show")(context, {"id": id})
                user_objs.append(context["user_obj"])
            except NotFound:
                pass
        else:
            user_list = get_action("user_list")(context, {"email": id})
            if user_list:
                # send reset emails for *all* user accounts with this email
                # (otherwise we'd have to silently fail - we can't tell the
                # user, as that would reveal the existence of accounts with
                # this email address)
                for user_dict in user_list:
                    get_action("user_show")(context, {"id": user_dict["id"]})
                    user_objs.append(context["user_obj"])

        if not user_objs:
            log.info("User requested reset link for unknown user: {}".format(id))

        for user_obj in user_objs:
            log.info("Emailing reset link to user: {}".format(user_obj.name))
            try:
                # DATAVIC-221: Do not create/send reset link if user was self-registered and currently pending
                if user_obj.is_pending() and not user_obj.reset_key:
                    h.flash_error(
                        _(
                            "Unable to send reset link - please contact the site administrator."
                        )
                    )
                    return h.redirect_to("/user/reset")
                else:
                    mailer.send_reset_link(user_obj)
            except MailerException as e:
                h.flash_error(
                    _(
                        "Error sending the email. Try again later "
                        "or contact an administrator for help"
                    )
                )
                log.exception(e)
                return h.redirect_to("/")
        # always tell the user it succeeded, because otherwise we reveal
        # which accounts exist or not
        h.flash_success(
            _(
                "A reset link has been emailed to you "
                "(unless the account specified does not exist)"
            )
        )
        return h.redirect_to("/")


class DataVicPerformResetView(user.PerformResetView):
    def _prepare(self, id):
        return super()._prepare(id)

    def get(self, id):
        # FIXME 403 error for invalid key is a non helpful page
        context = {
            "model": model,
            "session": model.Session,
            "user": id,
            "keep_email": True,
        }

        try:
            check_access("user_reset", context)
        except NotAuthorized as e:
            log.debug(str(e))
            abort(403, _("Unauthorized to reset password."))

        try:
            user_dict = get_action("user_show")(context, {"id": id})
            user_obj = context["user_obj"]
        except NotFound:
            abort(404, _("User not found"))

        g.reset_key = request.args.get("key")
        if not mailer.verify_reset_link(user_obj, g.reset_key):
            h.flash_error(_("Invalid reset key. Please try again."))
            abort(403)
        return render("user/perform_reset.html", {"user_dict": user_dict})

    def post(self, id):
        context, user_dict = self._prepare(id)
        try:
            # If you only want to automatically login new users,
            # check that user_dict['state'] == 'pending'
            context["reset_password"] = True
            new_password = super()._get_form_password()
            user_dict["password"] = new_password
            user_dict["reset_key"] = g.reset_key
            user_dict["state"] = model.State.ACTIVE
            user = get_action("user_update")(context, user_dict)
            user_obj = context["user_obj"]
            mailer.create_reset_key(user_obj)

            h.flash_success(_("Your password has been reset."))

            if not g.user:
                # log the user in programmatically
                set_repoze_user(user_dict["name"])
                return h.redirect_to("datavicuser.me")

            # DataVic customization
            # Redirect to different pages depending on user access
            if h.check_access("package_create"):
                return h.redirect_to("user.read", id=user["name"])
            else:
                return h.redirect_to("activity.user_activity", id=user["name"])
        except NotAuthorized:
            h.flash_error(_("Unauthorized to edit user %s") % id)
        except NotFound:
            h.flash_error(_("User not found"))
        except DataError:
            h.flash_error(_("Integrity Error"))
        except ValidationError as e:
            h.flash_error("%r" % e.error_dict)
        except ValueError as ve:
            h.flash_error(six.text_type(ve))


class DataVicUserEditView(user.EditView):
    def _prepare(self, id):
        return super()._prepare(id)

    # def get(self,  id=None, data=None, errors=None, error_summary=None):
    #     return super(DataVicUserEditView, self).get(id, data, errors, error_summary)

    def post(self, id=None):
        context, id = self._prepare(id)
        if not context["save"]:
            return self.get(id)

        current_user = id in (
            (
                ""
                if toolkit.current_user.is_anonymous
                else toolkit.current_user.id
            ),
            toolkit.current_user.name,
        )
        old_username = toolkit.current_user.name

        try:
            data_dict = clean_dict(unflatten(tuplize_dict(parse_params(request.form))))
            data_dict.update(
                clean_dict(unflatten(tuplize_dict(parse_params(request.files))))
            )

        except DataError:
            abort(400, _("Integrity Error"))
        data_dict.setdefault("activity_streams_email_notifications", False)

        context[u'message'] = data_dict.get(u'log_message', u'')
        data_dict[u'id'] = id
        email_changed = data_dict[u'email'] != toolkit.current_user.email

        if (data_dict[u'password1']
                and data_dict[u'password2']) or email_changed:

            # CUSTOM CODE to allow updating user pass for sysadmin without a sys pass
            self_update = data_dict["name"] == toolkit.current_user.name
            is_sysadmin = False if toolkit.current_user.is_anonymous else toolkit.current_user.sysadmin  # type: ignore

            if not is_sysadmin or self_update:
                identity = {
                    u'login': toolkit.current_user.name,
                    u'password': data_dict[u'old_password']
                }
                auth_user = authenticator.ckan_authenticator(identity)
                auth_username = auth_user.name if auth_user else ''

                if auth_username != toolkit.current_user.name:
                    errors = {
                        u'oldpassword': [_(u'Password entered was incorrect')]
                    }
                    error_summary = {_(u'Old Password'): _(u'incorrect password')}
                    return self.get(id, data_dict, errors, error_summary)

        try:
            user = get_action("user_update")(context, data_dict)
        except NotAuthorized:
            abort(403, _("Unauthorized to edit user %s") % id)
        except NotFound:
            abort(404, _("User not found"))
        except ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(id, data_dict, errors, error_summary)

        h.flash_success(_("Profile updated"))
        resp = h.redirect_to("user.read", id=user["name"])
        if current_user and data_dict["name"] != old_username:
            # Changing currently logged in user's name.
            # Update repoze.who cookie to match
            set_repoze_user(data_dict["name"], resp)
        return resp

    def get(self, id=None, data=None, errors=None, error_summary=None):
        context, id = self._prepare(id)
        data_dict = {"id": id}
        is_myself = toolkit.current_user.name == id
        is_sysadmin = toolkit.current_user.sysadmin

        if not any([is_sysadmin, is_myself]):
            return abort(403, _("Not authorized to see this page."))

        try:
            old_data = get_action("user_show")(context, data_dict)

            g.display_name = old_data.get("display_name")
            g.user_name = old_data.get("name")

            data = data or old_data

        except NotAuthorized:
            abort(403, _("Unauthorized to edit user %s") % "")
        except NotFound:
            abort(404, _("User not found"))

        errors = errors or {}
        vars = {"data": data, "errors": errors, "error_summary": error_summary}

        extra_vars = _extra_template_variables(
            {"model": model, "session": model.Session, "user": g.user}, data_dict
        )

        extra_vars["show_email_notifications"] = asbool(
            config.get("ckan.activity_streams_email_notifications")
        )
        vars.update(extra_vars)
        extra_vars["form"] = render(edit_user_form, extra_vars=vars)

        return render("user/edit.html", extra_vars)


def logged_in():
    # redirect if needed
    came_from = request.args.get("came_from", "")
    if h.url_is_local(came_from):
        return h.redirect_to(str(came_from))

    if g.user:
        return me()
    else:
        log.info("Login failed. Bad username or password.")
        return user.login()


def me():
    return (
        h.redirect_to(config.get("ckan.auth.route_after_login") or "dashboard.datasets")
        if h.check_access("package_create")
        else h.redirect_to("dataset.search")
    )


def approve(id):
    username = id
    try:
        data_dict = {"id": id}

        # Only sysadmins can activate a pending user
        check_access("sysadmin", {})

        old_data = get_action("user_show")({}, data_dict)
        username = old_data["name"]

        old_data["state"] = model.State.ACTIVE
        user = get_action("user_update")({"ignore_auth": True}, old_data)

        # Send new account approved email to user
        helpers.send_email(
            [user.get("email", "")],
            "new_account_approved",
            {
                "user_name": user.get("name", ""),
                "login_url": toolkit.url_for("user.login", qualified=True),
                "site_title": config.get("ckan.site_title"),
                "site_url": config.get("ckan.site_url"),
            },
        )

        h.flash_success(_("User approved"))

        return h.redirect_to("user.read", id=user["name"])
    except NotAuthorized:
        abort(403, _("Unauthorized to activate user."))
    except NotFound as e:
        abort(404, _("User not found"))
    except DataError:
        abort(400, _("Integrity Error"))
    except ValidationError as e:
        for field, summary in e.error_summary.items():
            h.flash_error(f"{field}: {summary}")

    return h.redirect_to("user.read", id=username)


def deny(id):
    try:
        data_dict = {"id": id}

        # Only sysadmins can activate a pending user
        check_access("sysadmin", {})

        user = get_action("user_show")({}, data_dict)
        # Delete denied user
        get_action("user_delete")({}, data_dict)

        # Send account requested denied email
        helpers.send_email(
            [user.get("email", "")],
            "new_account_denied",
            {
                "user_name": user.get("name", ""),
                "site_title": config.get("ckan.site_title"),
                "site_url": config.get("ckan.site_url"),
            },
        )

        h.flash_success(_("User Denied"))

        return h.redirect_to("user.read", id=user["name"])
    except NotAuthorized:
        abort(403, _("Unauthorized to reject user."))
    except NotFound as e:
        abort(404, _("User not found"))
    except DataError:
        abort(400, _("Integrity Error"))
    except ValidationError as e:
        h.flash_error("%r" % e.error_dict)


class RegisterView(MethodView):
    """
    This is copied from ckan_core views/user
    There is only 1 small change at the end which is to not login in registering users
    and redirect the user to the home page
    """

    def _prepare(self):
        context = {
            "model": model,
            "session": model.Session,
            "user": g.user,
            "auth_user_obj": g.userobj,
            "schema": _new_form_to_db_schema(),
            "save": "save" in request.form,
        }
        try:
            check_access("user_create", context)
        except NotAuthorized:
            toolkit.abort(403, _("Unauthorized to register as a user."))
        return context

    def post(self):
        context = self._prepare()
        try:
            data_dict = clean_dict(unflatten(tuplize_dict(parse_params(request.form))))
            data_dict.update(
                clean_dict(unflatten(tuplize_dict(parse_params(request.files))))
            )

        except DataError:
            toolkit.abort(400, _("Integrity Error"))

        context["message"] = data_dict.get("log_message", "")
        try:
            captcha.check_recaptcha(request)
        except captcha.CaptchaError:
            error_msg = _("Bad Captcha. Please try again.")
            h.flash_error(error_msg)
            return self.get(data_dict)

        try:
            get_action("user_create")(context, data_dict)
        except NotAuthorized:
            toolkit.abort(403, _("Unauthorized to create user %s") % "")
        except NotFound:
            toolkit.abort(404, _("User not found"))
        except ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(data_dict, errors, error_summary)

        if g.user:
            # #1799 User has managed to register whilst logged in - warn user
            # they are not re-logged in as new user.
            h.flash_success(
                _(
                    'User "%s" is now registered but you are still '
                    'logged in as "%s" from before'
                )
                % (data_dict["name"], g.user)
            )
            if authz.is_sysadmin(g.user):
                # the sysadmin created a new user. We redirect him to the
                # activity page for the newly created user
                return h.redirect_to("activity.user_activity", id=data_dict["name"])
            else:
                return toolkit.render("user/logout_first.html")

        # DATAVIC custom updates
        if helpers.user_is_registering():
            # If user is registering, do not login them and redirect them to the home page
            h.flash_success(
                toolkit._("Your requested account has been submitted for review")
            )
            resp = h.redirect_to("home.index")
        else:
            # log the user in programmatically
            resp = h.redirect_to("user.me")
            set_repoze_user(data_dict["name"], resp)
        return resp

    def get(self, data=None, errors=None, error_summary=None):
        self._prepare()

        if g.user and not data and not authz.is_sysadmin(g.user):
            # #1799 Don't offer the registration form if already logged in
            return toolkit.render("user/logout_first.html", {})

        form_vars = {
            "data": data or {},
            "errors": errors or {},
            "error_summary": error_summary or {},
        }

        extra_vars = {
            "is_sysadmin": authz.is_sysadmin(g.user),
            "form": toolkit.render(_new_user_form, form_vars),
        }
        return toolkit.render("user/new.html", extra_vars)


_edit_view = DataVicUserEditView.as_view(str("edit"))


def register_datavicuser_plugin_rules(blueprint):
    blueprint.add_url_rule(
        "/user/reset", view_func=DataVicRequestResetView.as_view(str("request_reset"))
    )
    blueprint.add_url_rule(
        "/user/reset/<id>",
        view_func=DataVicPerformResetView.as_view(str("perform_reset")),
    )
    blueprint.add_url_rule("/edit", view_func=_edit_view)
    blueprint.add_url_rule("/edit/<id>", view_func=_edit_view)
    blueprint.add_url_rule("/user/activate/<id>", view_func=approve)
    blueprint.add_url_rule("/user/deny/<id>", view_func=deny)
    blueprint.add_url_rule("/user/logged_in", view_func=logged_in)
    blueprint.add_url_rule("/user/me", view_func=me)
    blueprint.add_url_rule(
        "/user/register", view_func=RegisterView.as_view(str("register"))
    )


register_datavicuser_plugin_rules(datavicuser)
