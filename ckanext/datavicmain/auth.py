import ckan.plugins.toolkit as toolkit

from ckanext.datavicmain import helpers

_t = toolkit._

#   Need this decorator to force auth function to be checked for sysadmins aswell
#   (ref.: ckan/default/src/ckan/ckan/logic/__init__.py)


@toolkit.auth_sysadmins_check
@toolkit.auth_allow_anonymous_access
def datavic_user_update(context, data_dict=None):

    if toolkit.request and toolkit.get_endpoint() == ('user', 'perform_reset'):
        # Allow anonymous access to the user/reset path, i.e. password resets.
        return {'success': True}
    elif 'save' in context and context['save']:
        if 'email' in toolkit.request.params:
            schema = context.get('schema')

    return {'success': True}


@toolkit.auth_allow_anonymous_access
def datavic_user_reset(context, data_dict):
    if helpers.is_user_account_pending_review(context.get('user', None)):
        return {'success': False,
                'msg': _t('User %s not authorized to reset password') %
                (str(context.get('user')))}
    else:
        return {'success': True}


@toolkit.chained_auth_function
def datavic_package_update(next_auth, context, data_dict):
    if toolkit.request and toolkit.get_endpoint()[0] in ['dataset', 'package'] and toolkit.get_endpoint()[1] in ['read', 'edit', 'resource_read', 'resource_edit']:
        # Harvested dataset are not allowed to be updated, apart from sysadmins
        package_id = data_dict.get('id') if data_dict else toolkit.g.pkg_dict.get('id') if 'pkg_dict' in toolkit.g else None
        if package_id and helpers.is_dataset_harvested(package_id):
            return {'success': False,
                    'msg': _t('User %s not authorized to edit this harvested package') %
                    (str(context.get('user')))}

    return next_auth(context, data_dict)
