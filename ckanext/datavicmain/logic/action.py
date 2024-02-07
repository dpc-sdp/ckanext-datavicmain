import logging

import ckanapi

import ckan.types as types
import ckan.plugins.toolkit as toolkit

import ckanext.datavicmain.const as const
import ckanext.datavicmain.utils as utils
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
    utils.new_pending_user(context, data_dict)

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


@toolkit.chained_action
@toolkit.side_effect_free
def organization_show(
    next_: types.ChainedAction,
    context: types.Context,
    data_dict: types.DataDict,
) -> types.ActionResult.OrganizationShow:
    org_dict = next_(context, data_dict)

    if org_dict.get(const.ORG_VISIBILITY_FIELD) == const.ORG_RESTRICTED:
        toolkit.check_access(
            "datavic_restricted_organization", context, data_dict
        )

    return org_dict


@toolkit.chained_action
def organization_update(
    next_: types.ChainedAction,
    context: types.Context,
    data_dict: types.DataDict,
) -> types.ActionResult.OrganizationUpdate:
    if data_dict.get(const.ORG_VISIBILITY_FIELD) == const.ORG_RESTRICTED:
        toolkit.check_access(
            "datavic_restricted_organization", context, data_dict
        )

    return next_(context, data_dict)


@toolkit.chained_action
@toolkit.side_effect_free
def organization_list(
    next_: types.ChainedAction,
    context: types.Context,
    data_dict: types.DataDict,
) -> types.ActionResult.OrganizationList:
    if not data_dict.get("all_fields", None):
        return next_(context, data_dict)

    org_list = next_(context, data_dict)

    for org_dict in org_list:
        _hide_sensitive_fields(org_dict)

def _hide_sensitive_fields(org_dict: types.DataDict) -> None:
    allowed_fields = (
        "created",
        "description",
        "id",
        "image_display_url",
        "is_organization",
        "name",
        "title",
    )

    for field_name in list(org_dict.keys()):
        if field_name in allowed_fields:
            continue

        org_dict.pop(field_name, None)
