import logging

import ckanapi

import ckan.plugins.toolkit as toolkit
from ckan.model import State

import ckanext.datavicmain.utils as vicmain_utils
from ckanext.datavicmain.helpers import user_is_registering
from ckanext.datavicmain.logic.schema import custom_user_create_schema


log = logging.getLogger(__name__)

CONFIG_SYNCHRONIZED_ORGANIZATION_FIELDS = (
    "ckanext.datavicmain.synchronized_organization_fields"
)
DEFAULT_SYNCHRONIZED_ORGANIZATION_FIELDS = ["name", "title", "description"]


@toolkit.chained_action
def user_create(next_func, context, data_dict):
    """Create a pending user on registration"""
    is_registration = user_is_registering()

    if not is_registration:
        return next_func(context, data_dict)

    context["schema"] = custom_user_create_schema()

    user_dict = next_func(context, data_dict)
    data_dict["user_id"] = user_dict["id"]

    context.pop("schema", None)
    vicmain_utils.new_pending_user(context, data_dict)

    return user_dict


@toolkit.chained_action
def organization_update(next_, context, data_dict):
    from ckanext.syndicate import utils

    model = context["model"]

    old = model.Group.get(data_dict.get("id"))
    old_name = old.name if old else None

    result = next_(context, data_dict)

    if old_name == result["name"]:
        return result

    for profile in utils.get_profiles():
        ckan = utils.get_target(profile.ckan_url, profile.api_key)
        try:
            remote = ckan.action.organization_show(id=old_name)
        except ckanapi.NotFound:
            continue

        patch = {
            f: result[f]
            for f in toolkit.aslist(
                toolkit.config.get(
                    CONFIG_SYNCHRONIZED_ORGANIZATION_FIELDS,
                    DEFAULT_SYNCHRONIZED_ORGANIZATION_FIELDS,
                )
            )
        }
        ckan.action.organization_patch(id=remote["id"], **patch)

    return result
