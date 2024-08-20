from __future__ import annotations

import logging
from typing import Any

import ckanapi
from sqlalchemy import or_

import ckan.model as model
import ckan.types as types
import ckan.plugins.toolkit as toolkit

from ckanext.datavicmain import helpers, utils, const, jobs
from ckanext.datavicmain.helpers import user_is_registering
from ckanext.datavicmain.logic.schema import custom_user_create_schema

import ckan.lib.plugins as lib_plugins
import ckan.plugins.toolkit as toolkit
from ckan.common import g
from ckan.lib.dictization import model_dictize, model_save
from ckan.lib.navl.validators import not_empty
from ckan.logic import schema as ckan_schema, validate
from ckan.model import State
from ckan.types import Action, Context, DataDict
from ckan.types.logic import ActionResult

from ckanext.mailcraft.utils import get_mailer
from ckanext.mailcraft.exception import MailerException

import ckanext.datavic_iar_theme.helpers as theme_helpers
from ckanext.datavicmain.logic import schema as vic_schema

log = logging.getLogger(__name__)
user_is_registering = helpers.user_is_registering
ValidationError = toolkit.ValidationError
get_action = toolkit.get_action
_validate = toolkit.navl_validate

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


def resource_update(
    next_: Action, context: Context, data_dict: DataDict
) -> ActionResult.ResourceUpdate:
    try:
        result = next_(context, data_dict)
        return result
    except ValidationError as e:
        if "Virus checker" in e.error_dict:
            # If the error is due to a virus check, return the error
            raise e

        _show_errors_in_sibling_resources(context, data_dict)


@toolkit.chained_action
def resource_create(
    next_: Action, context: Context, data_dict: DataDict
) -> ActionResult.ResourceCreate:
    try:
        result = next_(context, data_dict)
        return result
    except ValidationError as e:
        if "Virus checker" in e.error_dict:
            # If the error is due to a virus check, return the error
            raise e

        _show_errors_in_sibling_resources(context, data_dict)


@toolkit.chained_action
def resource_delete(
    next_: Action, context: Context, data_dict: DataDict
) -> ActionResult.ResourceDelete:
    try:
        result = next_(context, data_dict)
        return result
    except ValidationError as e:
        _show_errors_in_sibling_resources(context, data_dict, e.error_dict)


def _show_errors_in_sibling_resources(
    context: Context, data_dict: DataDict
) -> Any:
    """Retrieves and raises validation errors for resources within the same package."""
    pkg_dict = toolkit.get_action("package_show")(
        context,
        {
            "id": data_dict.get("package_id")
            or model.Resource.get(data_dict["id"]).package_id  # type: ignore
        },
    )

    package_plugin = lib_plugins.lookup_package_plugin(pkg_dict["type"])

    _, errors = lib_plugins.plugin_validate(
        package_plugin,
        context,
        pkg_dict,
        context.get("schema") or package_plugin.update_package_schema(),
        "package_update",
    )

    resources_errors = errors.pop("resources", [])

    for i, resource_error in enumerate(resources_errors):
        if not resource_error:
            continue
        errors.update(
            {
                f"Field '{field}' in the resource '{pkg_dict['resources'][i]['name']}'": (
                    error
                )
                for field, error in resource_error.items()
            }
        )
    if errors:
        raise ValidationError(errors)


@toolkit.side_effect_free
def datavic_list_incomplete_resources(context, data_dict):
    """Retrieves a list of resources that are missing at least one required field."""
    try:
        pkg_type = data_dict.get("type", "dataset")
        resource_schema = toolkit.h.scheming_get_dataset_schema(pkg_type)[
            "resource_fields"
        ]
    except TypeError:
        raise toolkit.ValidationError(f"No schema for {pkg_type} package type")

    required_fields = [
        field["field_name"]
        for field in resource_schema
        if toolkit.h.scheming_field_required(field)
    ]

    missing_conditions = []
    for field in required_fields:
        model_attr = getattr(model.Resource, field)
        missing_conditions.append(or_(model_attr == None, model_attr == ""))

    q = (
        model.Session.query(model.Resource)
        .join(model.Package)
        .filter(model.Package.state == "active")
        .filter(model.Resource.state == "active")
        .filter(or_(*missing_conditions))
    )

    if data_dict.get("by_package", False):
        grouped_resources = {}
        for resource in q:
            missing_fields = [
                field
                for field in required_fields
                if not getattr(resource, field)
            ]
            resource_dict = {
                "id": resource.id,
                "missing_fields": missing_fields,
            }

            grouped_resources.setdefault(resource.package_id, []).append(
                resource_dict
            )

        results = [
            {"package_id": package_id, "resources": resources}
            for package_id, resources in grouped_resources.items()
        ]
        num_packages = len(grouped_resources)
    else:
        results = []
        package_ids = set()
        for resource in q:
            package_ids.add(resource.package_id)
            results.append(
                {
                    "id": resource.id,
                    "missing_fields": [
                        field
                        for field in required_fields
                        if not getattr(resource, field)
                    ],
                }
            )
        num_packages = len(package_ids)

    return {
        "num_resources": q.count(),
        "num_packages": num_packages,
        "results": results,
    }


@validate(vic_schema.delwp_data_request_schema)
def send_delwp_data_request(context, data_dict):
    """Send a notification to admin about a new data request"""
    mailer = get_mailer()

    data_dict.update(
        {
            "site_title": toolkit.config.get("ckan.site_title"),
            "site_url": toolkit.config.get("ckan.site_url"),
        }
    )

    pkg_title = data_dict["__extras"]["package_title"]
    user = g.userobj.fullname or g.user
    subject = f"Data request via VPS Data Directory - {pkg_title} requested by {user}"

    try:
        mailer.mail_recipients(
            subject,
            [toolkit.config["ckanext.datavicmain.data_request.contact_point"]],
            body=toolkit.render(
                "mailcraft/emails/request_delwp_data/body.txt",
                data_dict,
            ),
            body_html=toolkit.render(
                "mailcraft/emails/request_delwp_data/body.html",
                data_dict,
            ),
        )
    except MailerException:
        return {"success": False}

    return {"success": True}
