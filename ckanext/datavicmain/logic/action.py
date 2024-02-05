import logging
from typing import Any

import ckan.lib.plugins as lib_plugins
import ckan.plugins.toolkit as toolkit
import ckanapi
import ckanext.datavic_iar_theme.helpers as theme_helpers
from ckan import model
from ckan.lib.dictization import model_dictize, model_save, table_dictize
from ckan.lib.navl.validators import not_empty  # noqa
from ckan.logic import schema as ckan_schema
from ckan.logic import validate
from ckan.model import State
from ckan.types import Action, Context, DataDict
from ckan.types.logic import ActionResult
from ckanext.datavicmain import helpers, jobs
from ckanext.datavicmain.logic import schema as vic_schema
from ckanext.mailcraft.exception import MailerException
from ckanext.mailcraft.utils import get_mailer
from sqlalchemy import or_

import ckan.plugins.toolkit as toolkit
from ckan.model import State

import ckanext.datavicmain.utils as vicmain_utils
from ckanext.datavicmain.helpers import user_is_registering
from ckanext.datavicmain.logic.schema import custom_user_create_schema


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


@toolkit.chained_action
def resource_update(
    next_: Action, context: Context, data_dict: DataDict
) -> ActionResult.ResourceUpdate:
    try:
        result = next_(context, data_dict)
        return result
    except ValidationError:
        _show_errors_in_sibling_resources(context, data_dict)


@toolkit.chained_action
def resource_create(
    next_: Action, context: Context, data_dict: DataDict
) -> ActionResult.ResourceCreate:
    try:
        result = next_(context, data_dict)
        return result
    except ValidationError:
        _show_errors_in_sibling_resources(context, data_dict)


def _show_errors_in_sibling_resources(
    context: Context, data_dict: DataDict
) -> Any:
    """Retrieves and raises validation errors for resources within the same package."""
    pkg_dict = toolkit.get_action("package_show")(
        context, {"id": data_dict["package_id"]}
    )

    package_plugin = lib_plugins.lookup_package_plugin(pkg_dict["type"])

    _, errors = lib_plugins.plugin_validate(
        package_plugin,
        context,
        pkg_dict,
        context.get("schema") or package_plugin.update_package_schema(),
        "package_update",
    )

    resources_errors = errors["resources"]
    del errors["resources"]

    for i, resource_error in enumerate(resources_errors):
        if not resource_error:
            continue
        errors.update({
            f"Field '{field}' in the resource '{pkg_dict['resources'][i]['name']}'": (
                error
            )
            for field, error in resource_error.items()
        })
    if errors:
        raise ValidationError(errors)


@validate(vic_schema.delwp_data_request_schema)
def send_delwp_data_request(context, data_dict):
    """Send a notification to admin about a new data request"""
    mailer = get_mailer()

    data_dict.update({
        "site_title": toolkit.config.get("ckan.site_title"),
        "site_url": toolkit.config.get("ckan.site_url"),
    })

    try:
        mailer.mail_recipients(
            "Data request",
            [data_dict["contact_email"]],
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
            results.append({
                "id": resource.id,
                "missing_fields": [
                    field
                    for field in required_fields
                    if not getattr(resource, field)
                ],
            })
        num_packages = len(package_ids)

    return {
        "num_resources": q.count(),
        "num_packages": num_packages,
        "results": results,
    }
