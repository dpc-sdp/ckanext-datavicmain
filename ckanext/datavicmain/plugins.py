# Plugins for ckanext-datavicmain

import json
import time
import calendar
import jsonpickle
import copy
import logging
import ckan.authz as authz

import ckan.model           as model
import ckan.plugins         as p
import ckan.plugins.toolkit as toolkit
import ckan.logic           as logic

from ckanext.datavicmain import actions

import weberror

from ckan.common import config, request

_t = toolkit._

log1 = logging.getLogger(__name__)

from ckan import lib
from ckan.lib import base


workflow_enabled = False

# Conditionally import the the workflow extension helpers if workflow extension enabled in .ini
if "workflow" in config.get('ckan.plugins', False):
    from ckanext.workflow import helpers as workflow_helpers
    workflow_enabled = True


def parse_date(date_str):
    try:
        return calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
    except Exception, e:
        return None


def validator_email_not_in_use(user_email, context):
    user = context['user_obj']

    # If there is no change to email, no need to check it further..
    if not user.email == user_email:
        result = actions.email_in_use(user_email, context)
        if result:
            raise lib.navl.dictization_functions.Invalid(user_email + ' is already in use.')

    return user_email


#   Need this decorator to force auth function to be checked for sysadmins aswell
#   (ref.: ckan/default/src/ckan/ckan/logic/__init__.py)
@toolkit.auth_sysadmins_check
@toolkit.auth_allow_anonymous_access
def datavic_user_update(context, data_dict=None):
    if toolkit.c.controller == 'user' and toolkit.c.action == 'perform_reset':
        # Allow anonymous access to the user/reset path, i.e. password resets.
        return {'success': True}
    elif 'save' in context and context['save']:
        if 'email' in request.params:
            schema = context.get('schema')
            if not validator_email_not_in_use in schema['email']:
                schema['email'].append(validator_email_not_in_use)

    return {'success': True}


def is_iar():
    return toolkit.asbool(config.get('ckan.iar', False))


#   The code in this class was copied (& adjusted) from the CKAN 2.2 repository
class AuthMiddleware(object):
    def __init__(self, app, app_conf):
        self.app = app
    def __call__(self, environ, start_response):
        # if logged in via browser cookies or API key, all pages accessible
        if 'repoze.who.identity' in environ or self._get_user_for_apikey(environ) or not is_iar():
            return self.app(environ,start_response)
        else:
            # otherwise only login/reset and front pages are accessible
            if (environ['PATH_INFO'] == '/' or environ['PATH_INFO'] == '/user/login' or environ['PATH_INFO'] == '/user/_logout'
                                or '/user/reset' in environ['PATH_INFO'] or environ['PATH_INFO'] == '/user/logged_out'
                                or environ['PATH_INFO'] == '/user/logged_in' or environ['PATH_INFO'] == '/user/logged_out_redirect'):
                return self.app(environ,start_response)
            else:
                # http://rufuspollock.org/2006/09/28/wsgi-middleware/
                environ['wsgiorg.routing_args'] = '',{'action': 'login', 'controller': 'user'}
                return self.app(environ,start_response)

    def _get_user_for_apikey(self, environ):
        # Adapted from https://github.com/ckan/ckan/blob/625b51cdb0f1697add59c7e3faf723a48c8e04fd/ckan/lib/base.py#L396
        apikey_header_name = config.get(base.APIKEY_HEADER_NAME_KEY,
                                        base.APIKEY_HEADER_NAME_DEFAULT)
        apikey = environ.get(apikey_header_name, '')
        if not apikey:
            # For misunderstanding old documentation (now fixed).
            apikey = environ.get('HTTP_AUTHORIZATION', '')
        if not apikey:
            apikey = environ.get('Authorization', '')
            # Forget HTTP Auth credentials (they have spaces).
            if ' ' in apikey:
                apikey = ''
        if not apikey:
            return None
        apikey = unicode(apikey)
        # check if API key is valid by comparing against keys of registered users
        query = model.Session.query(model.User)
        user = query.filter_by(apikey=apikey).first()
        return user

class DatasetForm(p.SingletonPlugin, toolkit.DefaultDatasetForm):
    ''' A plugin that provides some metadata fields and
    overrides the default dataset form
    '''
    p.implements(p.ITemplateHelpers)
    p.implements(p.IConfigurable, inherit=True)
    p.implements(p.IConfigurer, inherit=True)
    p.implements(p.IDatasetForm, inherit=True)
    p.implements(p.IPackageController, inherit=True)
    # p.implements(p.IResourceController, inherit=True)
    p.implements(p.IRoutes, inherit=True)
    p.implements(p.IActions)
    p.implements(p.IAuthFunctions)
    p.implements(p.IMiddleware, inherit=True)

    def make_middleware(self, app, config):
        return AuthMiddleware(app, config)

    # IAuthFunctions
    def get_auth_functions(self):
        return {
            'user_update': datavic_user_update,
        }


    # IActions
    def get_actions(self):
        return {
            # DATAVICIAR-42: Override CKAN's core `user_create` method
            'user_create': actions.datavic_user_create,
        }


    # IRoutes
    def before_map(self, map):
        map.connect('dataset_historical', '/dataset/{id}/historical',
            controller='ckanext.datavicmain.controller:DataVicMainController', action='historical')
        return map



    ## helper methods ## 

    YES_NO_OPTIONS = ['yes', 'no',]

    WORKFLOW_STATUS_OPTIONS = ['draft', 'ready_for_approval', 'published', 'archived',]

    # NOTE: the of the Z in organization for consistency with usage throughout CKAN
    ORGANIZATION_VISIBILITY_OPTIONS = ['current', 'parent', 'child', 'family', 'all',]

    RESOURCE_EXTRA_FIELDS = [
        ('location', { 'label': 'Location'}),
        ('date_creation_acquisition', {'label': 'Date of Creation or Acquisition'}),
        # Last updated is a core field..
        # ('last_updated', {'label': 'Last Updated'}),
        ('update_frequency', {'label': 'Update Frequency'}),
        ('other_frequency_description', {'label': 'Other frequency description'}),
        ('public_release_date', {'label': 'Public Release Date'}),
        ('geographic_coverage', {'label': 'Geographic - Coverage'}),
        ('geodata_granularity', { 'label': 'Geodata - Granularity', }),
        ('geodata_granularity_other', { 'label': 'Geodata - Granularity - other', }),
        ('asgs', {'label': 'ASGS (Australian Statistical Geography Standard)'}),
        ('bounding_box', {'label': 'Bounding Box'}),
        ('vertical_coverage', {'label': 'Vertical Coverage'}),
        ('data_quality_trust_statement', {'label': 'Data Quality / Trust Statement'}),
        ('period_start', {'label': 'Temporal Coverage Start'}),
        ('period_end', {'label': 'Temporal Coverage End'}),
    ]

    # Format (tuple): ( 'field_id', { 'field_attribute': 'value' } )
    DATASET_EXTRA_FIELDS = [
        # ('last_modified_user_id',  {'label': 'Last Modified By'}),
        ('licensing_other',  {'label': 'Licensing - other'}),
        ('workflow_status', {'label': 'Workflow Status'}),
        ('workflow_status_notes',  {'label': 'Workflow Status Notes', 'field_type': 'textarea'}),
        # NOTE: the use of the Z in organization for consistency with usage throughout CKAN
        ('organization_visibility', {'label': 'Organisation Visibility'}),
        ('extract', {'label': 'Extract'}),
        ('reason_inactivity', {'label': 'Reason for Inactivity'}),
        ('date_inactive', {'label': 'Date Inactive'}),
        ('personal_information', {'label': 'Personal Information', 'description': 'Does the asset contain personal or sensitive personal information?', 'field_type': 'yes_no'}),
        ('personal_information_if_yes', {'label': "If 'yes'"}),
        ('business_classification', {'label': 'Business Classification'}),
        ('type_category', {'label': 'Type / Category'}),
        ('record_disposal_category', {'label': 'Record Disposal Category'}),
        ('disposal_category', {'label': 'Disposal Category'}),
        ('disposal_category_other', {'label': 'Disposal Category - other'}),
        ('disposal_class', {'label': 'Disposal Class'}),
        ('disposal_class_other', {'label': 'Disposal Class - other'}),
        ('retention_timeframe', {'label': 'Retention Timeframe'}),
        ('retention_timeframe_other', {'label': 'Retension Timeframe - other'}),
        ('owning_agency', {'label': 'Owning Agency'}),
        ('originator', {'label': 'Originator'}),
        ('custodian_contact_details', {'label': 'Custodian - contact details'}),
        ('nsi', {'label': 'National Interest or National Security Information (NSI)?', 'field_type': 'yes_no'}),
        ('nsi_yes', {'label': "If 'yes'"}),
        ('protective_marking', {'label': 'Protective Marking'}),
        ('protective_marking_other', {'label': 'Protective Marking - other'}),
        ('bil_confidentiality', {'label': 'Business Impact Level (BIL) - Confidentiality'}),
        ('bil_other', {'label': 'BIL - other'}),
        ('authorised_unlimited_public_release', {'label': 'Is the Information Asset authorised for unlimited public release?', 'field_type': 'yes_no'}),
        ('authorised_unlimited_public_release_no', {'label': 'If No'}),
        ('approver_authorisor', {'label': 'Approver / Authorisor (for unlimited public release of the information)'}),
        ('bil_integrity', {'label': 'Business Impact Level (BIL) - Integrity'}),
        ('bil_availability', {'label': 'Business Impact Level (BIL) - Availability'}),
        ('copyright_statement', {'label': 'Copyright Statement'}),
        ('disclaimer', {'label': 'Disclaimer'}),
        ('attribution_statement', {'label': 'Attribution Statement'}),
        ('program_url', {'label': 'Program URL'}),
        ('iar_entry_review_date', {'label': 'IAR entry review date'}),
        ('primary_purpose_of_collection', {'label': 'Purpose (primary purpose of collection)'}),
        ('related_information_asset', {'label': 'Related Information Asset', 'field_type': 'yes_no'}),
        ('type_of_relationship', {'label': 'Type of relationship'}),
        ('value', {'label': 'Value'}),
        ('use_constraints', {'label': 'Use constraints'}),
        ('disposal_requirements', {'label': 'Disposal requirements'}),
        ('user_administrator', {'label': 'User/ Administrator'}),
        ('access', {'label': 'Access'}),
        ('meet_mandatory_legal_obligations', {'label': 'Collected to meet mandatory legal or regulatory obligations?', 'field_type': 'yes_no'}),
        ('collection_method', {'label': 'Collection method'}),
        ('collection_validation', {'label': 'Collection validation'}),
        ('internal_scope_of_use', {'label': 'Internal scope of use'}),
        ('external_scope_of_use', {'label': 'External scope of use'}),
        ('offline_access', {'label': 'Off-line Access'}),
        ('supports_business_process', {'label': 'Supports Business Process'}),
        ('source_ict_system', {'label': 'Source ICT System'}),
    ]

    @classmethod
    def yes_no_options(cls):
        ''' This generator method is only usefull for creating select boxes. '''
        for option in cls.YES_NO_OPTIONS:
            yield { 'value': option, 'text': option.capitalize() }

    @classmethod
    def workflow_status_options(cls, current_workflow_status, owner_org):
        user = toolkit.c.user
        #log1.debug("\n\n\n*** workflow_status_options | current_workflow_status: %s | owner_org: %s | user: %s ***\n\n\n", current_workflow_status, owner_org, user)
        for option in workflow_helpers.get_available_workflow_statuses(current_workflow_status, owner_org, user):
            yield {'value': option, 'text': option.replace('_', ' ').capitalize()}

    @classmethod
    def organization_visibility_options(cls):
        for option in cls.ORGANIZATION_VISIBILITY_OPTIONS:
            yield { 'value': option, 'text': option.capitalize() }

    @classmethod
    def organization_list_objects(cls, org_names = []):
        ''' Make a action-api call to fetch the a list of full dict objects (for each organization) '''
        context = {
            'model': model,
            'session': model.Session,
            'user': toolkit.c.user,
        }

        options = { 'all_fields': True }
        if org_names and len(org_names):
            t = type(org_names[0])
            if   t is str:
                options['organizations'] = org_names
            elif t is dict:
                options['organizations'] = map(lambda org: org.get('name'), org_names)

        return logic.get_action('organization_list') (context, options)

    @classmethod
    def organization_dict_objects(cls, org_names = []):
        ''' Similar to organization_list_objects but returns a dict keyed to the organization name. '''
        results = {}
        for org in cls.organization_list_objects(org_names):
            results[org['name']] = org
        return results

    @classmethod
    def is_admin(cls, owner_org):
        if workflow_enabled:
            user = toolkit.c.userobj
            if authz.is_sysadmin(user.name):
                return True
            else:
                role = workflow_helpers.role_in_org(owner_org, user.name)
                if role == 'admin':
                    return True

    def is_sysadmin(self):
        user = toolkit.c.user
        if authz.is_sysadmin(user):
            return True

    def workflow_status_pretty(self, workflow_status):
        return workflow_status.replace('_', ' ').capitalize()

    def historical_resources_list(self, resource_list):
        sorted_resource_list = {}
        i = 0
        for resource in resource_list:
            i += 1
            if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
                    'period_start') != '':
                key = parse_date(resource.get('period_start')[:10]) or 'zzz' + str(i)
            else:
                key = 'zzz' + str(i)
            resource['key'] = key
            # print parser.parse(resource.get('period_start')).strftime("%Y-%M-%d") + " " + resource.get('period_start')
            sorted_resource_list[key] = resource

        list = sorted(sorted_resource_list.values(), key=lambda item: str(item.get('key')), reverse=True)
        # for item in list:
        #    print item.get('period_start') + " " + str(item.get('key'))
        return list

    def historical_resources_range(resource_list):
        range_from = ""
        from_ts = None
        range_to = ""
        to_ts = None
        for resource in resource_list:

            if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
                    'period_start') != '':
                ts = parse_date(resource.get('period_start')[:10])
                if ts and (from_ts is None or ts < from_ts):
                    from_ts = ts
                    range_from = resource.get('period_start')[:10]
            if resource.get('period_end') is not None and resource.get('period_end') != 'None' and resource.get(
                    'period_end') != '':
                ts = parse_date(resource.get('period_end')[:10])
                if ts and (to_ts is None or ts > to_ts):
                    to_ts = ts
                    range_to = resource.get('period_end')[:10]

        if range_from != "" and range_to != "":
            return range_from + " to " + range_to
        elif range_from != "" or range_to != "":
            return range_from + range_to
        else:
            return None

    def is_historical(self):
        if toolkit.c.action == 'historical':
            return True

    def get_formats(self, limit=100):
        try:
            # Get any additional formats added in the admin settings
            additional_formats = [x.strip() for x in config.get('ckan.datavic.authorised_resource_formats', []).split(',')]
            q = request.GET.get('q', '')
            list_of_formats = [x.encode('utf-8') for x in
                               logic.get_action('format_autocomplete')({}, {'q': q, 'limit': limit}) if x] + additional_formats
            list_of_formats = sorted(list(set(list_of_formats)))
            dict_of_formats = []
            for item in list_of_formats:
                if item == ' ' or item == '':
                    continue
                else:
                    dict_of_formats.append({'value': item.lower(), 'text': item.upper()})
            dict_of_formats.insert(0, {'value': '', 'text': 'Please select'})

        except Exception, e:
            return []
        else:
            return dict_of_formats

    def repopulate_user_role(self):
        if 'submit' in request.params:
            return request.params['role']
        else:
            return 'member'

    ## ITemplateHelpers interface ##

    def get_helpers(self):
        ''' Return a dict of named helper functions (as defined in the ITemplateHelpers interface).
        These helpers will be available under the 'h' thread-local global object.
        '''
        return {
            'organization_list_objects': self.organization_list_objects,
            'organization_dict_objects': self.organization_dict_objects,
            'dataset_extra_fields': self.DATASET_EXTRA_FIELDS,
            'resource_extra_fields': self.RESOURCE_EXTRA_FIELDS,
            'yes_no_options': self.yes_no_options,
            'workflow_status_options': self.workflow_status_options,
            'organization_visibility_options': self.organization_visibility_options,
            'is_admin': self.is_admin,
            'workflow_status_pretty': self.workflow_status_pretty,
            'historical_resources_list': self.historical_resources_list,
            'historical_resources_range': self.historical_resources_range,
            'is_historical': self.is_historical,
            'get_formats': self.get_formats,
            'is_sysadmin': self.is_sysadmin,
            'repopulate_user_role': self.repopulate_user_role,
        }

    ## IConfigurer interface ##
    def update_config_schema(self, schema):
        schema.update({
            'ckan.datavic.authorised_resource_formats': [
                toolkit.get_validator('ignore_missing'),
                unicode
            ],
        })

        return schema

    def update_config(self, config):
        ''' Setup the (fanstatic) resource library, public and template directory '''
        p.toolkit.add_public_directory(config, 'public')
        p.toolkit.add_template_directory(config, 'templates')
        p.toolkit.add_resource('public', 'ckanext-datavicmain')

    ## IConfigurable interface ##

    def configure(self, config):
        ''' Apply configuration options to this plugin '''
        pass

    ## IDatasetForm interface ##

    def is_fallback(self):
        '''
        Return True to register this plugin as the default handler for
        package types not handled by any other IDatasetForm plugin.
        '''
        return True

    def package_types(self):
        '''
        This plugin doesn't handle any special package types, it just
        registers itself as the default (above).
        '''
        return []

    def _modify_package_schema(self, schema):
        ''' Override CKAN's create/update schema '''

        # Define some closures as custom callbacks for the validation process

        from ckan.lib.navl.dictization_functions import missing, StopOnError, Invalid

        # DataVic: Helper function for adding extra dataset fields
        def append_field(extras_list, data, key):
            items = filter(lambda t: t['key'] == key, extras_list)
            if items:
                items[0]['value'] = data.get((key,))
            else:
                extras_list.append({ 'key': key, 'value': data.get((key,)) })
            return

        def after_validation_processor(key, data, errors, context):
            assert key[0] == '__after', 'This validator can only be invok ed in the __after stage'
            #raise Exception ('Breakpoint after_validation_processor')
            # Demo of howto create/update an automatic extra field 
            extras_list = data.get(('extras',))
            if not extras_list:
                extras_list = data[('extras',)] = []
            # Note Append "record_modified_at" field as a non-input field
            datestamp = time.strftime('%Y-%m-%d %T')
            items = filter(lambda t: t['key'] == 'record_modified_at', extras_list)
            if items:
                items[0]['value'] = datestamp
            else:
                extras_list.append({ 'key': 'record_modified_at', 'value': datestamp })

            # DataVic: Append extra fields as dynamic (not registered under modify schema) field
            for field in self.DATASET_EXTRA_FIELDS:
                append_field(extras_list, data, field[0])

            # DATAVIC-56
            if workflow_enabled:
                # Get the current workflow_status value for comparison..
                pkg = model.Package.get(data.get(('id',)))

                if pkg and 'workflow_status' in pkg.extras:
                    user = toolkit.c.userobj

                    adjusted_workflow_status = workflow_helpers.get_workflow_status_for_role(
                        pkg.extras['workflow_status'],
                        data.get(('workflow_status',), None),
                        user.name,
                        data.get(('owner_org',), None)
                    )

                    items = filter(lambda t: t['key'] == 'workflow_status', extras_list)
                    if items:
                        items[0]['value'] = adjusted_workflow_status
                    else:
                        extras_list.append({'key': 'workflow_status', 'value': adjusted_workflow_status})


        def before_validation_processor(key, data, errors, context):
            assert key[0] == '__before', 'This validator can only be invoked in the __before stage'
            #raise Exception ('Breakpoint before_validation_processor')
            # Note Add dynamic field (not registered under modify schema) "foo.x1" to the fields
            # we take into account. If we omitted this step, the ('__extras',) item would have 
            # been lost (along with the POSTed value). 
            # DataVic: Add extra fields..
            for field in self.DATASET_EXTRA_FIELDS:
                data[(field[0],)] = data[('__extras',)].get(field[0])
            pass

        # Add our custom_resource_text metadata field to the schema
        # schema['resources'].update({
        #     'custom_resource_text' : [ toolkit.get_validator('ignore_missing') ]
        # })
        # DataVic implementation of adding extra metadata fields to resources
        resources_extra_metadata_fields = {}
        for field in self.RESOURCE_EXTRA_FIELDS:
            # DataVic: no custom validators for extra metadata fields at the moment
            resources_extra_metadata_fields[field[0]] = [ toolkit.get_validator('ignore_missing') ]

        schema['resources'].update(resources_extra_metadata_fields)

        # Add callbacks to the '__after' pseudo-key to be invoked after all key-based validators/converters
        if not schema.get('__after'):
            schema['__after'] = []
        schema['__after'].append(after_validation_processor)

        # A similar hook is also provided by the '__before' pseudo-key with obvious functionality.
        if not schema.get('__before'):
            schema['__before'] = []
        # any additional validator must be inserted before the default 'ignore' one. 
        schema['__before'].insert(-1, before_validation_processor) # insert as second-to-last

        return schema

    def create_package_schema(self):
        schema = super(DatasetForm, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self):
        schema = super(DatasetForm, self).update_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def show_package_schema(self):
        schema = super(DatasetForm, self).show_package_schema()

        # Don't show vocab tags mixed in with normal 'free' tags
        # (e.g. on dataset pages, or on the search page)
        schema['tags']['__extras'].append(toolkit.get_converter('free_tags_only'))

        # Create a dictionary containing the extra fields..
        dict_extra_fields = {
            # Add our non-input field (created at after_validation_processor)
            'record_modified_at': [
                toolkit.get_converter('convert_from_extras'),
            ],
        }

        # Loop through our extra fields, adding them to the schema..
        # Applying the same validator to them for now..
        for field in self.DATASET_EXTRA_FIELDS:
            dict_extra_fields[field[0]] = [
                toolkit.get_converter('convert_from_extras'),
                toolkit.get_validator('ignore_missing')
            ]

        # Apply any specific rules / validators that we know of..
        #

        schema.update(dict_extra_fields)


        # Update Resource schema
        schema['resources'].update({
            'custom_resource_text' : [ toolkit.get_validator('ignore_missing') ],
            'period_start': [toolkit.get_converter('convert_from_extras'),
                             toolkit.get_validator('ignore_missing')],
            'period_end': [toolkit.get_converter('convert_from_extras'),
                           toolkit.get_validator('ignore_missing')],
        })


        # Append computed fields in the __after stage

        def f(k, data, errors, context):
            data[('baz_view',)] = u'I am a computed Baz'
            pass

        if not schema.get('__after'):
            schema['__after'] = []
        schema['__after'].append(f)

        return schema

    def setup_template_variables(self, context, data_dict):
        ''' Setup (add/modify/hide) variables to feed the template engine.
        This is done through through toolkit.c (template thread-local context object).
        '''
        super(DatasetForm, self).setup_template_variables(context, data_dict)
        c = toolkit.c
        c.helloworld_magic_number = 99
        if c.pkg_dict:
            c.pkg_dict['helloworld'] = { 'plugin-name': self.__class__.__name__ }

    # Note for all *_template hooks: 
    # We choose not to modify the path for each template (so we simply call the super() method). 
    # If a specific template's behaviour needs to be overriden, this can be done by means of 
    # template inheritance (e.g. Jinja2 `extends' or CKAN `ckan_extends')

    def new_template(self):
        return super(DatasetForm, self).new_template()

    def read_template(self):
        return super(DatasetForm, self).read_template()

    def edit_template(self):
        return super(DatasetForm, self).edit_template()

    def comments_template(self):
        return super(DatasetForm, self).comments_template()

    def search_template(self):
        return super(DatasetForm, self).search_template()

    def history_template(self):
        return super(DatasetForm, self).history_template()
    
    ## IPackageController interface ##
    
    def after_create(self, context, pkg_dict):
        log1.debug('after_create: Package %s is created', pkg_dict.get('name'))
        pass

    def after_update(self, context, pkg_dict):
        log1.debug('after_update: Package %s is updated', pkg_dict.get('name'))
        pass

    def after_show(self, context, pkg_dict):
        '''Convert dataset_type-typed parts of pkg_dict to a nested dict or an object.

        This is for display (template enviroment and api results) purposes only, 
        and should *not* affect the way the read schema is being used.

        :param context: The context under which this hook is invoked
        :type context: dict
        :param pkg_dict: The package dict  
        :type pkg_dict: dict

        :returns: None
        :raises: None
        
        '''

        is_validated = context.get('validate', True)
        for_view = context.get('for_view', False)
        
        log1.debug('after_show: Package %s is shown: view=%s validated=%s api=%s', 
            pkg_dict.get('name'), for_view, is_validated, context.get('api_version'))
        
        if not is_validated:
            # Noop: the extras are not yet promoted to 1st-level fields
            return

        # Add more (computed) items to pkg_dict ... 

        return
        #return pkg_dict
     
    def before_search(self, search_params):
        #search_params['q'] = 'extras_qoo:*';
        #search_params['extras'] = { 'ext_qoo': 'far' }
        return search_params
   
    def after_search(self, search_results, search_params):
        #raise Exception('Breakpoint')
        return search_results

    def before_index(self, pkg_dict):
        log1.debug('before_index: Package %s is indexed', pkg_dict.get('name'))
        return pkg_dict

    def before_view(self, pkg_dict):
        log1.debug('before_view: Package %s is prepared for view', pkg_dict.get('name'))

        # This hook can add/hide/transform package fields before sent to the template.
        
        # add some extras to the 2-column table
        
        dt = pkg_dict.get('dataset_type')

        extras = pkg_dict.get('extras', [])
        if not extras:
            pkg_dict['extras'] = extras

        # extras.append({ 'key': 'Music Title', 'value': pkg_dict.get('music_title', 'n/a') })
        # extras.append({ 'key': 'Music Genre', 'value': pkg_dict.get('music_genre', 'n/a') })

        # or we can translate keys ...
        
        field_key_map = {
            u'updated_at': _t(u'Updated'),
            u'created_at': _t(u'Created'),
        }
        for item in extras:
            k = item.get('key')
            item['key'] = field_key_map.get(k, k)
        
        return pkg_dict

