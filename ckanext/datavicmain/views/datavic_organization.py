from __future__ import annotations

import logging
from typing import Any, cast

from flask import Blueprint, Response
from flask.views import MethodView

import ckan.model as model
import ckan.plugins.toolkit as tk
import ckan.types as types
from ckan.logic import parse_params

from ckanext.mailcraft.exception import MailerException
from ckanext.mailcraft.utils import get_mailer

import ckanext.datavicmain.utils as vicmain_utils

log = logging.getLogger(__name__)

bp = Blueprint("datavic_org", __name__, url_prefix="/organization")
mailer = get_mailer()


def restricted_pages() -> None:
    """Check that the organisation exists and user has an access to manage it"""
    org_id = tk.request.view_args.get("org_id")

    if not org_id:
        return

    context = make_context()

    try:
        tk.get_action("organization_show")(context, {"id": org_id})
    except tk.ObjectNotFound:
        tk.abort(404, tk._("Not Found"))

    try:
        tk.check_access("group_edit_permissions", context, {"id": org_id})
    except tk.NotAuthorized:
        tk.abort(403, tk._("Not authorized"))


def make_context():
    return cast(
        types.Context,
        {
            "model": model,
            "session": model.Session,
            "user": tk.current_user.name,
        },
    )


class JoinOrgRequestView(MethodView):
    def post(self, org_id: str) -> Response:
        data_dict, errors = tk.navl_validate(
            parse_params(tk.request.form),
            {
                "organisation_role": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("one_of")(tk.h.datavic_get_org_roles()),  # type: ignore
                ]
            },
        )

        if errors:
            tk.h.flash_error(errors)
            return tk.redirect_to("organization.read", id=org_id)

        role = data_dict["organisation_role"]
        roles = tk.h.datavic_get_user_roles_in_org(tk.current_user.id, org_id)

        if role in roles:
            tk.h.flash_error(
                tk._(f"You already have a {role} role in this organization")
            )
            return tk.redirect_to("organization.read", id=org_id)

        if role == "admin" and "editor" not in roles:
            tk.h.flash_error(
                tk._(
                    "You need to have an Editor role in this organization to become an Administrator"
                )
            )
            return tk.redirect_to("organization.read", id=org_id)

        vicmain_utils.store_user_org_join_request(
            {
                "name": tk.current_user.name,
                "email": tk.current_user.email,
                "organisation_id": org_id,
                "organisation_role": role,
            }
        )

        tk.h.flash_success(
            tk._("Request sent to organisation Administrator for review")
        )
        return tk.redirect_to("organization.read", id=org_id)


class JoinOrgRequestListView(MethodView):
    def _before_request(self):
        restricted_pages()

    def get(self, org_id: str) -> str:
        self._before_request()

        try:
            group_dict = tk.get_action("organization_show")(
                make_context(), {"id": org_id}
            )
        except tk.ObjectNotFound:
            return tk.abort(404, tk._("Organization not found"))
        except tk.NotAuthorized:
            return tk.abort(403, tk._("Not authorized"))

        return tk.render(
            "organization/join_request_list.html",
            extra_vars={
                "data": self._filter_by_current_org(
                    group_dict, vicmain_utils.get_pending_org_access_requests()
                ),
                "group_dict": group_dict,
                "group_type": "organization",
            },
        )

    def _filter_by_current_org(
        self,
        group_dict: dict[str, Any],
        org_requests: list[vicmain_utils.OrgJoinRequest],
    ) -> list[vicmain_utils.OrgJoinRequest]:
        return [
            request
            for request in org_requests
            if request["organisation_id"]
            in [group_dict["id"], group_dict["name"]]
        ]


class ApproveRequestView(MethodView):
    """Approve user's request to join an organisation"""

    def _before_request(self):
        restricted_pages()

    def post(self, org_id: str) -> Response:
        self._before_request()

        self.context = make_context()

        data_dict, errors = tk.navl_validate(
            parse_params(tk.request.form),
            self.get_payload_schema(),
            self.context,
        )

        if errors:
            tk.h.flash_error(errors)
            return tk.redirect_to("datavic_org.request_list", org_id=org_id)

        vicmain_utils.remove_user_from_join_request_list(data_dict["username"])

        self.create_org_member(org_id, data_dict)
        self.send_email_notification(org_id, data_dict)

        tk.h.flash_success("User request has been approved")
        return tk.redirect_to("datavic_org.request_list", org_id=org_id)

    def create_org_member(
        self, org_id: str, data_dict: dict[str, Any]
    ) -> None:
        tk.get_action("member_create")(
            self.context,
            {
                "id": org_id,
                "object": data_dict["username"],
                "object_type": "user",
                "capacity": data_dict["role"],
            },
        )

    def send_email_notification(
        self, org_id: str, data_dict: dict[str, Any]
    ) -> None:
        organization = model.Group.get(org_id)
        user = model.User.get(data_dict["username"])
        role = data_dict["role"]

        # should not happen, but just in case
        if not organization or not user:
            return

        extra_vars = {
            "username": user.display_name,
            "fullname": user.fullname,
            "role": role,
            "org_name": organization.title,
            "org_url": tk.h.url_for(
                "organization.read", id=org_id, _external=True
            ),
            "site_url": tk.config["ckan.site_url"],
            "site_title": tk.config["ckan.site_title"],
        }

        try:
            mailer.mail_recipients(
                tk._(
                    f"Request for {role.title()} - {organization.title} access approved"
                ),
                [data_dict["email"]],
                body=tk.render(
                    "mailcraft/emails/organisation_access_request_approved/body.txt",
                    extra_vars,
                ),
                body_html=tk.render(
                    "mailcraft/emails/organisation_access_request_approved/body.html",
                    extra_vars,
                ),
            )
        except MailerException:
            log.error("Failed to send email notification")
            pass

    def get_payload_schema(self) -> types.Schema:
        """Create a schema to validate request payload"""
        return cast(
            types.Schema,
            {
                "role": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("one_of")(tk.h.datavic_get_org_roles()),  # type: ignore
                ],
                "username": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("user_id_or_name_exists"),
                ],
                "email": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("email_validator"),
                ],
            },
        )


class DenyRequestView(MethodView):
    """Deny user's request to join an organisation"""

    def _before_request(self):
        restricted_pages()

    def post(self, org_id: str) -> Response:
        self._before_request()

        data_dict, errors = tk.navl_validate(
            parse_params(tk.request.form),
            self.get_payload_schema(),
            make_context(),
        )

        if errors:
            tk.h.flash_error(errors)
            return tk.redirect_to("datavic_org.request_list", org_id=org_id)

        vicmain_utils.remove_user_from_join_request_list(data_dict["username"])
        self.send_email_notification(org_id, data_dict)

        tk.h.flash_success("User request has been denied")
        return tk.redirect_to("datavic_org.request_list", org_id=org_id)

    def send_email_notification(
        self, org_id: str, data_dict: dict[str, Any]
    ) -> None:
        organization = model.Group.get(org_id)
        user = model.User.get(data_dict["username"])
        role = data_dict["role"]

        # should not happen, but just in case
        if not organization or not user:
            return

        extra_vars = {
            "username": user.display_name,
            "fullname": user.fullname,
            "role": role,
            "org_name": organization.title,
            "org_url": tk.h.url_for(
                "organization.read", id=org_id, _external=True
            ),
            "reason": data_dict["reason"],
            "site_url": tk.config["ckan.site_url"],
            "site_title": tk.config["ckan.site_title"],
        }

        try:
            mailer.mail_recipients(
                tk._(
                    f"Request for {role.title()} - {organization.title} access denied"
                ),
                [data_dict["email"]],
                body=tk.render(
                    "mailcraft/emails/organisation_access_request_denied/body.txt",
                    extra_vars,
                ),
                body_html=tk.render(
                    "mailcraft/emails/organisation_access_request_denied/body.html",
                    extra_vars,
                ),
            )
        except MailerException:
            log.error("Failed to send email notification")
            pass

    def get_payload_schema(self) -> types.Schema:
        """Create a schema to validate request payload"""
        return cast(
            types.Schema,
            {
                "role": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("one_of")(tk.h.datavic_get_org_roles()),  # type: ignore
                ],
                "username": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("user_id_or_name_exists"),
                ],
                "email": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("email_validator"),
                ],
                "reason": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                ],
            },
        )


def register_plugin_rules(blueprint):
    blueprint.add_url_rule(
        "/access/request_join/<org_id>",
        view_func=JoinOrgRequestView.as_view("request_join"),
    )
    blueprint.add_url_rule(
        "/access/requests/<org_id>",
        view_func=JoinOrgRequestListView.as_view("request_list"),
    )
    blueprint.add_url_rule(
        "/access/approve/<org_id>",
        view_func=ApproveRequestView.as_view("approve_request"),
    )
    blueprint.add_url_rule(
        "/access/deny/<org_id>",
        view_func=DenyRequestView.as_view("deny_request"),
    )


register_plugin_rules(bp)
