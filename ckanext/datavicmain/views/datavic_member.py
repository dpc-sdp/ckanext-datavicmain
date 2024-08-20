from __future__ import annotations

from hmac import new
import logging
from typing import Any, cast, TypedDict

from flask import Blueprint

import ckan.types as types
import ckan.model as model
import ckan.logic as logic
import ckan.plugins.toolkit as tk
from ckan.lib.search import rebuild, commit
from ckan.views.user import delete as core_delete

log = logging.getLogger(__name__)
datavic_member = Blueprint(
    "datavic_member", __name__, url_prefix="/vic-member"
)


class MemberData(TypedDict):
    user: model.User
    role: str


@datavic_member.route("/modal/remove-org-member", methods=["GET"])
def get_member_remove_modal():
    data_dict = logic.parse_params(tk.request.args)

    org_id = tk.get_or_bust(data_dict, "org_id")
    user_id = tk.get_or_bust(data_dict, "user_id")

    try:
        assert tk.check_access(
            "organization_member_create", make_context(), {"id": org_id}
        )
    except tk.NotAuthorized:
        return tk.abort(403, tk._("Unauthorized to delete group members"))

    user_packages = get_user_packages_for_organisation(org_id, user_id)
    extra_vars = {
        "user_packages": user_packages,
        "org_id": org_id,
        "user_id": user_id,
    }

    if user_packages:
        extra_vars["members_options"] = get_new_member_options(
            get_organisation_editors_and_admins(org_id), user_id
        )

    return tk.render(
        "datavic_member/modal/remove_org_member_content.html",
        extra_vars=extra_vars,
    )


@datavic_member.route("/modal/remove-user", methods=["GET"])
def get_user_remove_modal():
    data_dict = logic.parse_params(tk.request.args)

    user_id = tk.get_or_bust(data_dict, "user_id")
    context = make_context()

    try:
        assert tk.check_access("user_delete", context, {"id": user_id})
    except tk.NotAuthorized:
        return tk.abort(403, tk._("Unauthorized to delete user"))

    return tk.render(
        "datavic_member/modal/remove_user_content.html",
        extra_vars={
            "user_orgs": get_user_orgs_with_packages(user_id),
            "user_id": user_id,
        },
    )


def make_context() -> types.Context:
    return cast(
        types.Context,
        {
            "model": model,
            "session": model.Session,
            "user": tk.current_user.name,
        },
    )


def get_user_orgs_with_packages(user_id: str) -> list[dict[str, Any]]:
    context = make_context()
    user_orgs = tk.get_action("organization_list_for_user")(
        context, {"id": user_id, "permission": "create_dataset"}
    )

    orgs_with_packages = []

    for org in user_orgs:
        packages = get_user_packages_for_organisation(org["id"], user_id)

        if packages:
            orgs_with_packages.append(org)

    return orgs_with_packages


def get_user_packages_for_organisation(
    org_id: str, user_id: str
) -> list[model.Package]:
    packages = get_user_packages(user_id)

    if not packages:
        return []

    return [package for package in packages if package.owner_org == org_id]


def get_user_packages(user_id: str) -> list[model.Package]:
    return (
        model.Session.query(model.Package)
        .filter(model.Package.creator_user_id == user_id)
        .all()
    )


def get_organisation_editors_and_admins(org_id: str) -> list[MemberData]:
    organisation = model.Group.get(org_id)

    if not organisation:
        return []

    result = []

    for member in organisation.member_all:
        if member.table_name != "user":
            continue

        if member.state != model.State.ACTIVE:
            continue

        if member.capacity not in ["editor", "admin"]:
            continue

        user = model.User.get(member.table_id)

        # This should never happen, but just in case
        if not user:
            continue

        result.append({"user": user, "role": member.capacity})

    return result


def get_new_member_options(
    member_list: list[MemberData], current_user_id: str
) -> list[dict[str, Any]]:
    return [
        {
            "text": f"{member['user'].display_name} ({member['role']})",
            "value": member["user"].id,
        }
        for member in member_list
        if member["user"].id != current_user_id
        and member["user"].state == model.State.ACTIVE
    ]


@datavic_member.route("/remove-org-member", methods=["POST"])
def remove_member():
    data_dict = logic.parse_params(tk.request.form)

    org_id: str = tk.get_or_bust(data_dict, "org_id")
    user_id: str = tk.get_or_bust(data_dict, "user_id")
    new_member_id: str | None = data_dict.get("new_member")  # type: ignore

    if new_member_id:
        reassign_user_packages(org_id, user_id, new_member_id)
        tk.h.flash_notice(tk._("User's packages have been reassigned."))

    context = make_context()

    try:
        tk.get_action("group_member_delete")(
            context, {"id": org_id, "user_id": user_id}
        )
    except tk.NotAuthorized:
        return tk.abort(
            403, tk._("Unauthorized to delete group %s members") % ""
        )
    except tk.ObjectNotFound:
        return tk.abort(404, tk._("Organization not found"))

    tk.h.flash_notice(tk._("Organisation member has been deleted."))
    return tk.h.redirect_to("organization.members", id=org_id)


def reassign_user_packages(
    org_id: str, user_id: str, target_user: str
) -> list[model.Package]:
    packages = get_user_packages_for_organisation(org_id, user_id)

    user = model.User.get(target_user)

    if not user:
        raise tk.ObjectNotFound("Target user not found")

    if user.state != model.State.ACTIVE:
        raise tk.ValidationError("Target user is not active")

    target_roles = tk.h.datavic_get_user_roles_in_org(target_user, org_id)

    if not target_roles or target_roles == ["member"]:
        raise tk.ValidationError(
            "Target user is not an editor or admin of the organization"
        )

    result = []

    for package in packages:
        package.creator_user_id = user.id

        try:
            rebuild(package.id, force=True, defer_commit=True, quiet=False)
        except Exception as e:
            log.error(
                "Error rebuilding search index for package %s: %s",
                package.id,
                e,
            )

        result.append(package)

    commit()
    model.Session.commit()

    return result


@datavic_member.route("/remove-user", methods=["POST"])
def remove_user():
    data_dict = logic.parse_params(tk.request.form)
    user_id = tk.get_or_bust(data_dict, "user_id")

    if get_user_orgs_with_packages(user_id):
        return tk.abort(
            400,
            tk._(
                "User still has packages in organisations. Please reassign them before deleting the user."
            ),
        )

    return core_delete(user_id)
