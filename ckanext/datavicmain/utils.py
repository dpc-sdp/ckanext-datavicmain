from __future__ import annotations

from typing import Any, TypedDict

import ckan.types as types
import ckan.model as model
import ckan.plugins.toolkit as tk


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

    return flake["data"]["users"]


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
    users = get_pending_org_access_requests()

    for user in users:
        if user["name"] == user_data["name"]:
            return users

    users.append(
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
            "data": {"users": users},
        },
    )

    return users


def _create_empty_pending_users_flake():
    tk.get_action("flakes_flake_create")(
        {"ignore_auth": True},
        {
            "author_id": None,
            "name": PENDING_USERS_FLAKE_NAME,
            "data": {"users": []},
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
