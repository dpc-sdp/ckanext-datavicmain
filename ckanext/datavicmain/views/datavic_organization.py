from __future__ import annotations

import logging

from flask import Blueprint, Response
from flask.views import MethodView

import ckan.plugins.toolkit as tk
from ckan.logic import parse_params

import ckanext.datavicmain.utils as vicmain_utils

log = logging.getLogger(__name__)

bp = Blueprint("datavic_org", __name__)


class JoinOrgRequestView(MethodView):
    def post(self, org_id: str) -> Response:
        available_roles = [
            role["value"]
            for role in tk.h.datavic_get_registration_org_role_options()
        ]

        data_dict, errors = tk.navl_validate(
            parse_params(tk.request.form),
            {
                "organisation_role": [
                    tk.get_validator("not_empty"),
                    tk.get_validator("unicode_safe"),
                    tk.get_validator("one_of")(available_roles),
                ]
            },
        )

        if errors:
            tk.h.flash_error(errors)
            return tk.redirect_to("organization.read", id=org_id)

        vicmain_utils.store_user_org_join_request(
            {
                "name": tk.g.userobj.name,
                "email": tk.g.userobj.email,
                "organisation_id": org_id,
                "organisation_role": data_dict["organisation_role"],
            }
        )

        return tk.redirect_to("organization.read", id=org_id)


class JoinOrgRequestListView(MethodView):
    def get(self):
        data = vicmain_utils.get_pending_org_access_requests()

        return tk.render(
            "admin/join_org_request_list.html", extra_vars={"data": data}
        )


def register_plugin_rules(blueprint):
    blueprint.add_url_rule(
        "/access/request_join/<org_id>",
        view_func=JoinOrgRequestView.as_view("request_join"),
    )
    blueprint.add_url_rule(
        "/access/requests-list",
        view_func=JoinOrgRequestListView.as_view("request_list"),
    )

register_plugin_rules(bp)
