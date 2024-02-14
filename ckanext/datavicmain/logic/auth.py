import ckan.plugins.toolkit as tk

from ckan import authz
from ckan.types import Context, DataDict, AuthResult

from ckanext.datavicmain import helpers


#   Need this decorator to force auth function to be checked for sysadmins aswell
#   (ref.: ckan/default/src/ckan/ckan/logic/__init__.py)


@tk.auth_sysadmins_check
@tk.auth_allow_anonymous_access
def user_update(context, data_dict=None):
    if tk.request and tk.get_endpoint() == ('datavicuser', 'perform_reset'):
        # Allow anonymous access to the user/reset path, i.e. password resets.
        return {'success': True}
    elif 'save' in context and context['save']:
        if 'email' in tk.request.args:
            schema = context.get('schema')

    return {"success": True}


@tk.auth_allow_anonymous_access
def user_reset(context, data_dict):
    if helpers.is_user_account_pending_review(context.get('user', None)):
        return {'success': False,
                'msg': tk._('User %s not authorized to reset password') %
                (str(context.get('user')))}
    else:
        return {"success": True}


@tk.chained_auth_function
def package_update(next_auth, context, data_dict):
    if tk.request and tk.get_endpoint()[0] in ['dataset', 'package'] and tk.get_endpoint()[1] in ['read', 'edit', 'resource_read', 'resource_edit']:
        # Harvested dataset are not allowed to be updated, apart from sysadmins
        package_id = data_dict.get('id') if data_dict else tk.g.pkg_dict.get('id') if 'pkg_dict' in tk.g else None
        if package_id and helpers.is_dataset_harvested(package_id):
            return {'success': False,
                    'msg': tk._('User %s not authorized to edit this harvested package') %
                    (str(context.get('user')))}

    return next_auth(context, data_dict)


def datavic_toggle_organization_uploads(context, data_dict):
    return {"success": False}


def user_show(context: Context, data_dict: DataDict) -> AuthResult:
    if tk.request and tk.get_endpoint() == ("datavicuser", "perform_reset"):
        return {"success": True}
    user_id = authz.get_user_id_for_username(data_dict.get("id"))
    is_myself = tk.current_user.name == data_dict.get("id")
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
