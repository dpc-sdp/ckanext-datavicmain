from __future__ import annotations

import logging

import ckanapi

import ckan.model as model
import ckan.types as types
import ckan.plugins.toolkit as toolkit

from ckanext.datavicmain import utils, const, jobs
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

    if not context.get(
        "_skip_restriction_check"
    ) and not utils.user_has_org_access(org_dict["id"], context["user"]):
        raise toolkit.ObjectNotFound

    return org_dict


@toolkit.chained_action
def organization_update(
    next_: types.ChainedAction,
    context: types.Context,
    data_dict: types.DataDict,
) -> types.ActionResult.OrganizationUpdate:
    """Changing visibility field should change the visibility datasets. We are
    using permissions labels, so we have to reindex all the datasets to index
    new labels into solr"""
    current_visibility = model.Group.get(data_dict["id"]).extras.get(
        const.ORG_VISIBILITY_FIELD, const.ORG_VISIBILITY_DEFAULT
    )

    org_dict = next_(context, data_dict)

    new_visibility = utils.get_extra_value(
        const.ORG_VISIBILITY_FIELD, org_dict
    )

    if new_visibility != current_visibility:
        log.info(
            "The organisation %s visibility has changed. Rebuilding datasets index",
            org_dict["id"],
        )
        toolkit.enqueue_job(jobs.reindex_organization, [org_dict["id"]])

    return org_dict


@toolkit.chained_action
@toolkit.side_effect_free
def organization_list(
    next_: types.ChainedAction,
    context: types.Context,
    data_dict: types.DataDict,
) -> types.ActionResult.OrganizationList:
    """Restrict organisations. Force all_fields and include_extras, because we
    need visibility field to be here.
    Throw out extra fields later if it's not all_fields initially"""
    all_fields = data_dict.pop("all_fields", False)

    data_dict.update({"all_fields": True, "include_extras": True})

    context["_skip_restriction_check"] = True

    org_list: types.ActionResult.OrganizationList = next_(context, data_dict)

    filtered_orgs = _hide_restricted_orgs(context, org_list)

    if not all_fields:
        return [org["name"] for org in filtered_orgs]

    return filtered_orgs


def _hide_restricted_orgs(
    context: types.Context,
    org_list: types.ActionResult.OrganizationList,
) -> types.ActionResult.OrganizationList:
    """Throw out organisation if it's restricted and user doesn't have access to it"""
    result = []

    for org in org_list:
        if not utils.user_has_org_access(org["id"], context["user"]):
            continue

        result.append(org)

    return result
