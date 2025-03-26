from __future__ import annotations

import logging
from typing import Any, cast

import ckanapi
from sqlalchemy import or_

import ckan.model as model
import ckan.types as types
from ckan.lib import uploader
import ckan.lib.plugins as lib_plugins
import ckan.plugins.toolkit as toolkit
from ckan.logic import validate
from ckan.types import Action, Context, DataDict

from ckanext.syndicate.utils import get_profiles, get_target
from ckanext.datavic_harvester.harvesters.base import get_resource_size
from ckanext.mailcraft.utils import get_mailer
from ckanext.mailcraft.exception import MailerException

from ckanext.datavicmain.logic import schema as vic_schema
from ckanext.datavicmain import helpers, utils, const
from ckanext.datavicmain.helpers import user_is_registering
from ckanext.datavicmain.logic.schema import custom_user_create_schema

log = logging.getLogger(__name__)
user_is_registering = helpers.user_is_registering
ValidationError = toolkit.ValidationError
get_action = toolkit.get_action

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
    """
    Add organization fields synchronization logic.
    Add prohibition on changing the organization visibility field.
    """
    old = toolkit.get_action("organization_show")(
        {"ignore_auth": True},
        {"id": data_dict["id"]}
    )
    old_name = old["name"] if old else None
    old_visibility = model.Group.get(data_dict["id"]).extras.get(
        const.ORG_VISIBILITY_FIELD, const.ORG_VISIBILITY_DEFAULT
    )

    result = next_(context, data_dict)
    new_visibility = utils.get_extra_value(const.ORG_VISIBILITY_FIELD, result)

    if new_visibility != old_visibility:
        raise ValidationError(
            f"The organisation {result['id']} visibility can't be changed after creation."
        )

    tracked_fields: list[str] = toolkit.aslist(
        toolkit.config.get(
            CONFIG_SYNCHRONIZED_ORGANIZATION_FIELDS,
            DEFAULT_SYNCHRONIZED_ORGANIZATION_FIELDS,
        )
    )

    if not _is_org_changed(old, result, tracked_fields):
        return result

    for profile in get_profiles():
        ckan = get_target(profile.ckan_url, profile.api_key)
        try:
            remote = ckan.action.organization_show(id=old_name)
        except ckanapi.NotFound:
            continue

        patch = {
            f: result[f]
            for f in tracked_fields if f in result
        }

        if 'image_url' in tracked_fields and result.get('image_display_url'):
            grp_uloader: uploader.PUploader = uploader.get_uploader('group')
            file_data = None
            with open(grp_uloader.storage_path + '/' + result['image_url'], 'rb') as f:
                file_data = f.read()

            patch['id'] = remote['id']
            ckan.call_action('organization_patch', data_dict=patch, files={
                "image_upload": (result['image_url'], file_data)})
        else:
            ckan.action.organization_patch(id=remote["id"], **patch)

    return result


def _is_org_changed(
    old_org: dict[str, Any], new_org: dict[str, Any], tracked_fields: list[str]
) -> bool:
    for field_name in tracked_fields:
        if old_org.get(field_name) != new_org.get(field_name):
            return True

    return False


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
@toolkit.side_effect_free
def organization_list(
    next_: types.ChainedAction,
    context: types.Context,
    data_dict: types.DataDict,
) -> types.ActionResult.OrganizationList:
    """Restrict organisations. Force all_fields and include_extras, because we
    need visibility field to be here.
    Throw out extra fields later if it's not all_fields initially"""
    all_fields = data_dict.get("all_fields", False)

    if all_fields:
        data_dict.update({"include_extras": True})

    context["_skip_restriction_check"] = True

    org_list: types.ActionResult.OrganizationList = next_(context, data_dict)

    if not all_fields:
        orgs = model.Session.query(model.Group)\
            .filter(model.Group.name.in_(org_list))

        # Intead of all all_fields, lets get the ID from the Objet as it much faster
        org_list = [{'id': org.id , 'name': org.name} for org in orgs]

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


@toolkit.chained_action
def resource_update(
    next_: Action, context: Context, data_dict: DataDict
) -> types.Action.ActionResult.ResourceUpdate:
    try:
        if not data_dict.get("filesize"):
            resource = model.Resource.get(data_dict.get("id"))
            if data_dict["url_type"] == "upload":
                data_dict["filesize"] = resource.size
            else:
                data_dict["filesize"] = get_resource_size(data_dict["url"])

        result = next_(context, data_dict)
        return result
    except ValidationError as valid_errors:
        _show_errors_in_sibling_resources(context, data_dict, valid_errors)


@toolkit.chained_action
def resource_create(
    next_: Action, context: Context, data_dict: DataDict
) -> types.Action.ActionResult.ResourceCreate:
    try:
        result = next_(context, data_dict)
        return result
    except ValidationError as valid_errors:
        _show_errors_in_sibling_resources(context, data_dict, valid_errors)


def _show_errors_in_sibling_resources(
    context: Context, data_dict: DataDict, valid_errors: DataDict
) -> Any:
    """Retrieves and raises validation errors for resources within the same package."""
    try:
        error_dict = cast(
            "list[type.ErrorDict]", valid_errors.error_dict['resources'])[-1]
    except (KeyError, IndexError):
        error_dict = valid_errors.error_dict

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

    resources_errors = errors.get("resources", [])

    for i, resource_error in enumerate(resources_errors):
        if not resource_error or data_dict.get("id") == pkg_dict["resources"][i]["id"]:
            continue
        error_dict.update(
            {
                f"Field '{field}' in the resource '{pkg_dict['resources'][i]['name']}'": (
                    error
                )
                for field, error in resource_error.items()
            }
        )
    if error_dict:
        raise ValidationError(error_dict)


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
    user = toolkit.g.userobj.fullname or toolkit.g.user
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


@validate(vic_schema.datatables_view_prioritize)
def datavic_datatables_view_prioritize(
    context: Context, data_dict: DataDict
) -> types.DataDict:
    """Check if the datatables view is prioritized over the recline view.
    If not, swap their order.
    """
    toolkit.check_access("vic_datatables_view_prioritize", context, data_dict)

    resource_id = data_dict["resource_id"]
    res_views = sorted(
        model.Session.query(model.ResourceView)
        .filter(model.ResourceView.resource_id == resource_id)
        .all(),
        key=lambda x: x.order,
    )
    datatables_views = _filter_views(res_views, "datatables_view")
    recline_views = _filter_views(res_views, "recline_view")

    if not (
        datatables_views
        and recline_views
        and datatables_views[0].order > recline_views[0].order
    ):
        return {"updated": False}

    datatables_views[0].order, recline_views[0].order = (
        recline_views[0].order,
        datatables_views[0].order,
    )
    order = [view.id for view in sorted(res_views, key=lambda x: x.order)]
    toolkit.get_action("resource_view_reorder")(
        {"ignore_auth": True}, {"id": resource_id, "order": order}
    )
    return {"updated": True}


@toolkit.chained_action
def resource_view_create(next_, context, data_dict):
    result = next_(context, data_dict)
    if data_dict["view_type"] == "datatables_view":
        toolkit.get_action("datavic_datatables_view_prioritize")(
            {"ignore_auth": True}, {"resource_id": data_dict["resource_id"]}
        )
    return result


def _filter_views(
    res_views: list[model.ResourceView], view_type: str
) -> list[model.ResourceView]:
    """Return a list of views with the given view type."""
    return [view for view in res_views if view.view_type == view_type]
