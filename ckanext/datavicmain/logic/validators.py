import ckan.plugins.toolkit as toolkit
import logging


log = logging.getLogger(__name__)


def datavic_tag_string(key, data, errors, context):

    request = toolkit.request if repr(toolkit.request) != '<LocalProxy unbound>' and hasattr(toolkit.request, 'params') else None

    if request:
        end_point = toolkit.get_endpoint()
        if end_point and end_point[0] == 'dataset' and end_point[1] in ['new', 'edit']:
            toolkit.get_validator('not_empty')(key, data, errors, context)
            return

    toolkit.get_validator('ignore_missing')(key, data, errors, context)

