import ckan.plugins.toolkit as toolkit

from ckan import authz
from ckan.types import Context, DataDict, AuthResult

from ckanext.datavicmain import helpers

_t = toolkit._

#   Need this decorator to force auth function to be checked for sysadmins aswell
#   (ref.: ckan/default/src/ckan/ckan/logic/__init__.py)


@toolkit.auth_sysadmins_check
@toolkit.auth_allow_anonymous_access
def user_update(context, data_dict=None):
    if toolkit.request and toolkit.get_endpoint() == ("datavicuser", "perform_reset"):
        # Allow anonymous access to the user/reset path, i.e. password resets.
        return {"success": True}
    elif "save" in context and context["save"]:
        if "email" in toolkit.request.args:
            schema = context.get("schema")

    return {"success": True}


@toolkit.auth_allow_anonymous_access
def user_reset(context, data_dict):
    if helpers.is_user_account_pending_review(context.get("user", None)):
        return {
            "success": False,
            "msg": _t("User %s not authorized to reset password")
            % (str(context.get("user"))),
        }
    else:
        return {"success": True}


@toolkit.chained_auth_function
def package_update(next_auth, context, data_dict):
    if (
        toolkit.request
        and toolkit.get_endpoint()[0] in ["dataset", "package"]
        and toolkit.get_endpoint()[1]
        in ["read", "edit", "resource_read", "resource_edit"]
    ):
        # Harvested dataset are not allowed to be updated, apart from sysadmins
        package_id = (
            data_dict.get("id")
            if data_dict
            else toolkit.g.pkg_dict.get("id")
            if "pkg_dict" in toolkit.g
            else None
        )
        if package_id and helpers.is_dataset_harvested(package_id):
            return {
                "success": False,
                "msg": _t("User %s not authorized to edit this harvested package")
                % (str(context.get("user"))),
            }

    return next_auth(context, data_dict)


def datavic_toggle_organization_uploads(context, data_dict):
    return {"success": False}


def user_show(context: Context, data_dict: DataDict) -> AuthResult:
    if toolkit.request and toolkit.get_endpoint() == ("datavicuser", "perform_reset"):
        return {"success": True}
    user_id = authz.get_user_id_for_username(data_dict.get("id"))
    is_myself = toolkit.current_user.name == data_dict.get("id")
    is_sysadmin = authz.is_sysadmin(toolkit.current_user.name)

    if is_sysadmin or is_myself:
        return {"success": True}

    orgs = toolkit.get_action("organization_list_for_user")(
        {"user": toolkit.current_user.name}, {"permission": "admin"}
    )
    for org in orgs:
        members = toolkit.get_action("member_list")(
            {}, {"id": org.get("id"), "object_type": "user"}
        )
        member_ids = [member[0] for member in members]

        if user_id in member_ids:
            return {"success": True}

    return {"success": False}


def _has_user_capacity_in_org(org_id: str, roles: list) -> bool:
    """ Check if the current user has the necessary capacity in the certain
        organization

    Args:
        org_id (str): id of the organization 
        roles (list): list of necessary member roles in the organization

    Returns:
        bool: True if the current user has the necessary capacity in the certain
        organization, False - otherwise
    """
    if authz.users_role_for_group_or_org(
        group_id=org_id,
        user_name=toolkit.current_user.name) in roles:
        return True
    return False


@toolkit.chained_auth_function
def package_activity_list(next_auth, context, data_dict):
    pkg_dict = toolkit.get_action("package_show")(
        context,
        {"id": data_dict["id"]},
    )
    allowed_roles = ["admin", "editor"]
    is_user_collaborator = authz.user_is_collaborator_on_dataset(
        toolkit.current_user.id, pkg_dict["id"], allowed_roles
    )
    has_user_capacity = _has_user_capacity_in_org(
        pkg_dict["owner_org"], allowed_roles
    )

    if has_user_capacity or is_user_collaborator:
        return next_auth(context, data_dict)
    return {"success": False}


@toolkit.chained_auth_function
def organization_activity_list(next_auth, context, data_dict):
    allowed_roles = ["admin", "editor"]
    if _has_user_capacity_in_org(data_dict["id"], allowed_roles):
        return next_auth(context, data_dict)
    return {"success": False}
