RESOURCE_EXTRA_FIELDS = [
    # Last updated is a core field..
    # ('last_updated', {'label': 'Last Updated'}),
    ('filesize', {'label': 'Filesize'}),
    ('release_date', {'label': 'Release Date', 'field_type': 'date'}),
    ('period_start', {'label': 'Temporal Coverage Start', 'field_type': 'date'}),
    ('period_end', {'label': 'Temporal Coverage End', 'field_type': 'date'}),
    ('data_quality', {'label': 'Data Quality Statement', 'field_type': 'textarea'}),
    ('attribution', {'label': 'Attribution Statement', 'field_type': 'textarea'}),
]

# Format (tuple): ( 'field_id', { 'field_attribute': 'value' } )
DATASET_EXTRA_FIELDS = [
    # ('last_modified_user_id',  {'label': 'Last Modified By'}),
    ('extract', {'label': 'Abstract', 'field_type': 'textarea', 'required': True}),
    ('primary_purpose_of_collection', {'label': 'Purpose', 'field_type': 'textarea'}),
    ('workflow_status', {'label': 'Workflow Status'}),
    ('workflow_status_notes', {'label': 'Workflow Status Notes', 'field_type': 'textarea'}),
    # NOTE: the use of the Z in organization for consistency with usage throughout CKAN
    ('organization_visibility', {'label': 'Organisation Visibility'}),
    # Public Release is managed using the core CKAN Private field (true/false - private/public)
    ('category', {'label': 'Category', 'required': True}),
    ('agency_program_domain', {'label': 'Agency Program/Domain'}),

    # Data Owner - agency_program
    ('data_owner', {'label': 'Data Owner', 'field_group': 'maintainer'}),
    # Data Custodian
    # Role
    ('role', {'label': 'Role', 'field_group': 'maintainer'}),
    # Email
    # Uses CKAN core field `maintainer_email`

    # License
    ('custom_licence_text', {'label': 'License - other', 'field_group': 'licence'}),
    ('custom_licence_link', {'label': 'Custom license link', 'field_group': 'licence'}),

    # Personal Data (Privacy)
    ('personal_information', {
                                'label': 'Personal Data (Privacy)',
                                'description': '',
                                'field_type': 'select',
                                'options': [
                                    {'value': '', 'text': 'Please select'},
                                    {'value': 'not_yet', 'text': 'Not yet assessed'},
                                    {'value': 'yes', 'text': 'Yes'},
                                    {'value': 'yes_de_identified', 'text': 'Yes - with de-identified data'},
                                    {'value': 'no', 'text': 'No'},
                                ],
                                'required': True
                              }),

    # Access
    ('access', {'label': 'Access',
                'field_type': 'select',
                'options': [
                    {'value': '', 'text': 'Please select'},
                    {'value': 'yes', 'text': 'Yes'},
                    {'value': 'no', 'text': 'No'},
                    {'value': 'not_yet', 'text': 'Not yet assessed'},
                ],
                'required': True
                }),
    # Access - description
    ('access_description', {'label': 'Access - description', 'field_type': 'textarea'}),

    ('protective_marking', {'label': 'Protective Marking', 'field_type': 'select',
                            'options': [
                                {'value': '', 'text': 'Please select'},
                                {'value': 'Protected', 'text': 'Protected'},
                                {'value': 'Unclassified : Sensitive : Vic Cabinet',
                                 'text': 'Unclassified : Sensitive : Vic Cabinet'},
                                {'value': 'Unclassified : Sensitive', 'text': 'Unclassified : Sensitive'},
                                {'value': 'Unclassified : Sensitive : Personal',
                                 'text': 'Unclassified : Sensitive : Personal'},
                                {'value': 'Unclassified : Sensitive : Legal',
                                 'text': 'Unclassified : Sensitive : Legal'},
                                {'value': 'Unclassified : For Office Use Only',
                                 'text': 'Unclassified : For Office Use Only'},
                                {'value': 'Unclassified', 'text': 'Unclassified'},
                                {'value': 'Public Domain', 'text': 'Public Domain'},
                            ],
                            'required': True
                            }),

    # Business Impact Level - Confidentiality Breach
    ('bil_confidentiality', {'label': 'Business Impact Level - Confidentiality Breach',
                'field_type': 'select',
                'options': [
                    {'value': '', 'text': 'Please select'},
                    {'value': 'not_yet', 'text': 'Not yet assessed'},
                    {'value': 'negligible', 'text': 'Negligible'},
                    {'value': 'low', 'text': 'Low'},
                    {'value': 'moderate_medium', 'text': 'Moderate/Medium'},
                    {'value': 'major_high', 'text': 'Major/High'},
                    {'value': 'extreme_very_high', 'text': 'Extreme/Very High'},
                ]}),
    # Business Impact Level - Confidentiality Breach Description
    ('bil_confidentiality_description', {'label': 'Business Impact Level - Confidentiality Breach description', 'field_type': 'textarea'}),

    # Business Impact Level - Availability
    ('bil_availability', {'label': 'Business Impact Level - Availability',
                'field_type': 'select',
                'options': [
                    {'value': '', 'text': 'Please select'},
                    {'value': 'not_yet', 'text': 'Not yet assessed'},
                    {'value': 'negligible', 'text': 'Negligible'},
                    {'value': 'low', 'text': 'Low'},
                    {'value': 'moderate_medium', 'text': 'Moderate/Medium'},
                    {'value': 'major_high', 'text': 'Major/High'},
                    {'value': 'extreme_very_high', 'text': 'Extreme/Very High'},
                ]}),
    # Business Impact Level - Availability description
    ('bil_availability_description', {'label': 'Business Impact Level - Availability description', 'field_type': 'textarea'}),

    # Business Impact Level - Integrity
    ('bil_integrity', {'label': 'Business Impact Level - Integrity',
                'field_type': 'select',
                'options': [
                    {'value': '', 'text': 'Please select'},
                    {'value': 'not_yet', 'text': 'Not yet assessed'},
                    {'value': 'negligible', 'text': 'Negligible'},
                    {'value': 'low', 'text': 'Low'},
                    {'value': 'moderate_medium', 'text': 'Moderate/Medium'},
                    {'value': 'major_high', 'text': 'Major/High'},
                    {'value': 'extreme_very_high', 'text': 'Extreme/Very High'},
                ]}),
    # Business Impact Level - Integrity description
    ('bil_integrity_description', {'label': 'Business Impact Level - Integrity description', 'field_type': 'textarea'}),

    ('date_created_data_asset', {'label': 'Created (Data Asset)', 'field_type': 'date', 'required': True}),
    # Published (Metadata Record) (CKAN date published to data dir)
    ('date_modified_data_asset', {'label': 'Last Modified (Data Asset)', 'field_type': 'date'}),
    # Update Frequency
    ('update_frequency', {'label': 'Update Frequency',
                       'field_type': 'select',
                       'options': [
                           {'value': '', 'text': 'Please select'},
                           {'value': 'continual', 'text': 'Continual'},
                           {'value': 'daily', 'text': 'Daily'},
                           {'value': 'weekly', 'text': 'Weekly'},
                           {'value': 'fortnightly', 'text': 'Fortnightly'},
                           {'value': 'monthly', 'text': 'Monthly'},
                           {'value': 'quarterly', 'text': 'Quarterly'},
                           {'value': 'biannually', 'text': 'Biannually'},
                           {'value': 'annually', 'text': 'Annually'},
                           {'value': 'asNeeded', 'text': 'As Needed'},
                           {'value': 'irregular', 'text': 'Irregular'},
                           {'value': 'notPlanned', 'text': 'Not Planned'},
                           {'value': 'unknown', 'text': 'Unknown'},
                       ],
                      'required': True
                      }),
    # Full Metadata URL
    ('full_metadata_url', {'label': 'Full Metadata URL'}),

    # Source ICT System/Container
    ('source_ict_system', {'label': 'Source ICT System'}),
]


def get_options(option_list):
    options = []
    if option_list is not None:
        for option in option_list:
            options.append(option.get('value'))
    return options


def get_option_label(type, field, value):
    if type == 'dataset':
        schema = DATASET_EXTRA_FIELDS
    else:
        schema = RESOURCE_EXTRA_FIELDS

    for element in schema:
        if element[0] == field:
            schema_field = element
            break

    if schema_field and 'options' in schema_field[1]:
        for option in schema_field[1]['options']:
            if option['value'] == value:
                value = option['text']
                break
    return value
