import ckan.plugins.toolkit as tk

from ckanext.datavicmain import helpers, const


#   Need this decorator to force auth function to be checked for sysadmins aswell
#   (ref.: ckan/default/src/ckan/ckan/logic/__init__.py)


@tk.auth_sysadmins_check
@tk.auth_allow_anonymous_access
def user_update(context, data_dict=None):
    if tk.request and tk.get_endpoint() == ('user', 'perform_reset'):
        # Allow anonymous access to the user/reset path, i.e. password resets.
        return {'success': True}
    elif 'save' in context and context['save']:
        if 'email' in tk.request.args:
            schema = context.get('schema')

    return {'success': True}


@tk.auth_allow_anonymous_access
def user_reset(context, data_dict):
    if helpers.is_user_account_pending_review(context.get('user', None)):
        return {'success': False,
                'msg': tk._('User %s not authorized to reset password') %
                (str(context.get('user')))}
    else:
        return {'success': True}


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


def datavic_restricted_organization(context, data_dict):
    if data_dict.get(const.ORG_VISIBILITY_FIELD) == const.ORG_UNRESTRICTED:
        return {"success": True}

    return tk.check_access("sysadmin", context)
