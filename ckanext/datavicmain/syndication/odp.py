import ckan.plugins.toolkit as tk

from ckanext.alias.utils import parse_alias_field
from ckanext.alias.config import get_alias_fieldname

def prepare_package_for_odp(package_id, data_dict):
    _extract_extras(data_dict)
    pkg_dict = tk.get_action("package_show")(
        {"ignore_auth": True},
        {"id": package_id},
    )

    resources = pkg_dict.get("resources", [])

    resources[:] = [
        # don't synchronize hash, because it will prevent resource's ingestion
        # into datastore
        dict(res, hash="")
        for res in resources if not tk.asbool(res.get("private"))
    ]

    ## Update resources
    for res in resources:
        res["package_id"] = data_dict["name"]
    data_dict.pop('resources')
    data_dict['resources'] = resources

    ## Update groups
    groups = data_dict.pop('groups')
    data_dict['groups'] = []
    for group in groups:
        group.pop('id')
        data_dict['groups'].append(group)

    return data_dict


def _extract_extras(data_dict):
    extras = data_dict.pop("extras")

    for extra in extras:
        data_dict[extra["key"]] = extra["value"]
