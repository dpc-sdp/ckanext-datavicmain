import ckan
import ckan.logic as logic
import ckan.lib.dictization.model_dictize as model_dictize
import ckan.lib.dictization.model_save as model_save
import logging
from ckan import lib
from ckan.common import c, request

_validate = ckan.lib.navl.dictization_functions.validate
_check_access = logic.check_access
ValidationError = logic.ValidationError

log1 = logging.getLogger(__name__)


def email_in_use(user_email, context):
    model = context['model']
    session = context['session']
    return session.query(model.User).filter_by(email=user_email).first()


def user_email_unique(user_email, context):
    result = email_in_use(user_email, context)
    if result:
        raise lib.navl.dictization_functions.Invalid('Email address ' + user_email + ' already in use for user: ' + result.name)

    return user_email


def datavic_user_create(context, data_dict):
    model = context['model']
    schema = context.get('schema') or logic.schema.default_user_schema()
    # DATAVICIAR-42: Add unique email validation
    schema['email'].append(user_email_unique)
    session = context['session']

    _check_access('user_create', context, data_dict)

    data, errors = _validate(data_dict, schema, context)

    if errors:
        session.rollback()
        raise ValidationError(errors)

    # user schema prevents non-sysadmins from providing password_hash
    if 'password_hash' in data:
        data['_password'] = data.pop('password_hash')

    user = model_save.user_dict_save(data, context)

    # Flush the session to cause user.id to be initialised, because
    # activity_create() (below) needs it.
    session.flush()

    activity_create_context = {
        'model': model,
        'user': context['user'],
        'defer_commit': True,
        'ignore_auth': True,
        'session': session
    }
    activity_dict = {
        'user_id': user.id,
        'object_id': user.id,
        'activity_type': 'new user',
    }
    logic.get_action('activity_create')(activity_create_context, activity_dict)

    if not context.get('defer_commit'):
        model.repo.commit()

    # A new context is required for dictizing the newly constructed user in
    # order that all the new user's data is returned, in particular, the
    # api_key.
    #
    # The context is copied so as not to clobber the caller's context dict.
    user_dictize_context = context.copy()
    user_dictize_context['keep_apikey'] = True
    user_dictize_context['keep_email'] = True
    user_dict = model_dictize.user_dictize(user, user_dictize_context)

    context['user_obj'] = user
    context['id'] = user.id

    model.Dashboard.get(user.id)  # Create dashboard for user.

    log1.debug('Created user {name}'.format(name=user.name))
    return user_dict
