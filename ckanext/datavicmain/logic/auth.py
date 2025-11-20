import ckan.plugins.toolkit as tk
from ckan import authz
from ckan.types import AuthResult, Context, DataDict

from ckanext.datavicmain import helpers


@tk.auth_allow_anonymous_access
def user_reset(context, data_dict):
    if helpers.is_user_account_pending_review(context.get("user", None)):
        return {
            "success": False,
            "msg": (
                tk._("User %s not authorized to reset password")
                % (str(context.get("user")))
            ),
        }
    else:
        return {"success": True}


@tk.chained_auth_function
def package_update(next_auth, context, data_dict):
    if (
        tk.request
        and tk.get_endpoint()[0] in ["dataset", "package"]
        and tk.get_endpoint()[1]
        in ["read", "edit", "resource_read", "resource_edit"]
    ):
        # Harvested dataset are not allowed to be updated, apart from sysadmins
        package_id = (
            data_dict.get("id")
            if data_dict
            else tk.g.pkg_dict.get("id") if "pkg_dict" in tk.g else None
        )
        if package_id and helpers.is_dataset_harvested(package_id):
            return {
                "success": False,
                "msg": (
                    tk._(
                        "User %s not authorized to edit this harvested package"
                    )
                    % (str(context.get("user")))
                ),
            }

    return next_auth(context, data_dict)


def datavic_toggle_organization_uploads(context, data_dict):
    return {"success": False}


def user_show(context: Context, data_dict: DataDict) -> AuthResult:
    if tk.request and (
        tk.get_endpoint() == ("datavicuser", "perform_reset")
        or tk.get_endpoint() == ("activity", "user_activity")
    ):
        return {"success": True}

    if tk.current_user.is_anonymous:
        return {"success": False}

    user_id = authz.get_user_id_for_username(data_dict.get("id"))
    is_myself = data_dict.get("id") in (
        tk.current_user.name,
        tk.current_user.id,
    )
    is_sysadmin = authz.is_sysadmin(tk.current_user.name)

    if is_sysadmin or is_myself:
        return {"success": True}

    orgs = tk.get_action("organization_list_for_user")(
        {"user": tk.current_user.name}, {"permission": "admin"}
    )
    for org in orgs:
        members = tk.get_action("member_list")(
            {}, {"id": org.get("id"), "object_type": "user"}
        )
        member_ids = [member[0] for member in members]

        if user_id in member_ids:
            return {"success": True}

    return {"success": False}


def _has_user_capacity_in_org(org_id: str, roles: list) -> bool:
    """Check if the current user has the necessary capacity in the certain
        organization

    Args:
        org_id (str): id of the organization
        roles (list): list of necessary member roles in the organization

    Returns:
        bool: True if the current user has the necessary capacity in the certain
        organization, False - otherwise
    """
    if (
        authz.users_role_for_group_or_org(
            group_id=org_id, user_name=tk.current_user.name
        )
        in roles
    ):
        return True
    return False


@tk.chained_auth_function
def package_activity_list(next_auth, context, data_dict):
    pkg_dict = tk.get_action("package_show")(
        context,
        {"id": data_dict["id"]},
    )
    allowed_roles = ["admin", "editor"]
    is_user_collaborator = authz.user_is_collaborator_on_dataset(
        tk.current_user.id, pkg_dict["id"], allowed_roles
    )
    has_user_capacity = _has_user_capacity_in_org(
        pkg_dict["owner_org"], allowed_roles
    )

    if has_user_capacity or is_user_collaborator:
        return next_auth(context, data_dict)
    return {"success": False}


@tk.chained_auth_function
def organization_activity_list(next_auth, context, data_dict):
    allowed_roles = ["admin", "editor"]
    if _has_user_capacity_in_org(data_dict["id"], allowed_roles):
        return next_auth(context, data_dict)
    return {"success": False}
