from __future__ import annotations
from itertools import chain

from typing import Any, TypedDict

import ckan.types as types
import ckan.model as model
import ckan.plugins.toolkit as tk

import ckanext.datavicmain.const as const


PENDING_USERS_FLAKE_NAME = "datavic:organization:join_request"


class OrgJoinRequest(TypedDict):
    name: str
    email: str
    organisation_id: str
    organisation_role: str


def org_uploads_flake_name() -> str:
    """Name flake with a list of organizations where uploads are allowed."""
    return "datavic:organization:uploads_allowed:list"


def get_pending_org_access_requests() -> list[OrgJoinRequest]:
    try:
        flake = tk.get_action("flakes_flake_lookup")(
            {"ignore_auth": True},
            {"author_id": None, "name": PENDING_USERS_FLAKE_NAME},
        )
    except tk.ObjectNotFound:
        _create_empty_pending_users_flake()
        return []

    return flake["data"]["org_requests"]


def new_pending_user(
    context: types.Context, data_dict: dict[str, Any]
) -> None:
    """Create an activity and a membership for a new pending user. Sends a
    notification emails to related admins"""
    org_role = (
        data_dict["organisation_role"]
        if data_dict["organisation_role"] != "not-sure"
        else "member"
    )

    context["ignore_auth"] = True

    tk.get_action("activity_create")(
        context,
        {
            "user_id": data_dict["user_id"],
            "object_id": data_dict["user_id"],
            "activity_type": "new user",
        },
    )

    tk.get_action("member_create")(
        context,
        {
            "id": data_dict["organisation_id"],
            "object": data_dict["user_id"],
            "object_type": "user",
            "capacity": org_role,
        },
    )

    notify_about_pending_user(data_dict)


def store_user_org_join_request(
    user_data: dict[str, Any],
) -> list[dict[str, Any]]:
    requests = get_pending_org_access_requests()

    for req in requests:
        if (
            req["name"] == user_data["name"]
            and req["organisation_id"] == user_data["organisation_id"]
        ):
            return requests

    requests.append(
        OrgJoinRequest(
            name=user_data["name"],
            email=user_data["email"],
            organisation_id=user_data["organisation_id"],
            organisation_role=user_data["organisation_role"],
        )
    )

    notify_about_org_join_request(
        user_data["name"], user_data["organisation_id"]
    )

    tk.get_action("flakes_flake_override")(
        {"ignore_auth": True},
        {
            "author_id": None,
            "name": PENDING_USERS_FLAKE_NAME,
            "data": {"org_requests": requests},
        },
    )

    return requests


def remove_user_from_join_request_list(username: str) -> bool:
    users = get_pending_org_access_requests()

    tk.get_action("flakes_flake_override")(
        {"ignore_auth": True},
        {
            "author_id": None,
            "name": PENDING_USERS_FLAKE_NAME,
            "data": {
                "org_requests": [
                    user for user in users if user["name"] != username
                ]
            },
        },
    )

    return True


def _create_empty_pending_users_flake():
    tk.get_action("flakes_flake_create")(
        {"ignore_auth": True},
        {
            "author_id": None,
            "name": PENDING_USERS_FLAKE_NAME,
            "data": {"org_requests": []},
        },
    )


def notify_about_pending_user(data_dict: dict[str, Any]) -> None:
    tk.h.datavic_send_email(
        [
            x.strip()
            for x in tk.config.get(
                "ckan.datavic.request_access_review_emails", []
            ).split(",")
        ],
        "new_account_requested",
        {
            "user_name": data_dict["name"],
            "user_url": tk.url_for(
                "user.read", id=data_dict["name"], qualified=True
            ),
            "site_title": tk.config.get("ckan.site_title"),
            "site_url": tk.config.get("ckan.site_url"),
        },
    )


def notify_about_org_join_request(username: str, orgname: str) -> None:
    try:
        org_admins = tk.get_action("member_list")(
            {"ignore_auth": True}, {"id": orgname, "capacity": "admin"}
        )
    except tk.ObjectNotFound:
        return

    recipients = [model.User.get(user[0]).email for user in org_admins]
    org_title = model.Group.get(orgname).title

    tk.h.datavic_send_email(
        recipients,
        "new_organisation_access_request",
        {
            "username": username,
            "org_name": org_title,
            "link": tk.h.url_for("home.index", qualified=True),
        },
    )


def user_has_org_access(org_id: str, user_id: str):
    """Organisation could be restricted. Only sysadmins and org members should
    have an access to the restricted organisation"""

    if not is_org_restricted(org_id):
        return True

    user_orgs = tk.get_action("organization_list_for_user")(
        {"ignore_auth": True}, {"id": user_id}
    )

    for org in user_orgs:
        if org_id in [org["id"], org["name"]]:
            return True

    return False


def is_org_restricted(org_id: str) -> bool:
    """Check if the organization is restricted"""
    is_restricted = bool(
        model.Session.query(model.GroupExtra)
        .filter(model.GroupExtra.group_id == org_id)
        .filter(model.GroupExtra.key == const.ORG_VISIBILITY_FIELD)
        .filter(model.GroupExtra.value == const.ORG_RESTRICTED)
        .first()
    )

    return is_restricted or bool(get_org_restricted_parents(org_id))


def get_org_restricted_parents(org_id: str) -> list[model.Group]:
    """Return a list of organisation restricted parents hierarchy. Restriction
    is inherited, so if the org is restricted all child orgs will be treated as
    restricted as well"""
    organization = model.Group.get(org_id)

    if not organization:
        return []

    parent_orgs = organization.get_parent_group_hierarchy("organization")

    if not parent_orgs:
        return []

    found_restricted = False
    restricted_parents = []

    for parent_org in parent_orgs:
        if not found_restricted and (
            parent_org.extras.get(const.ORG_VISIBILITY_FIELD)
            == const.ORG_RESTRICTED
        ):
            found_restricted = True

        if found_restricted:
            restricted_parents.append(parent_org)

    return restricted_parents


def get_extra_value(
    key: str, org_dict: types.ActionResult.OrganizationUpdate
) -> Any | None:
    for extra in org_dict.get("extras", []):
        if extra["key"] != key:
            continue

        return extra["value"]
