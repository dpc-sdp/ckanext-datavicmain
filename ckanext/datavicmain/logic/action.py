from __future__ import annotations

import logging
from typing import Any, OrderedDict

import ckanapi
from sqlalchemy import or_

import ckan.lib.plugins as lib_plugins
import ckan.plugins.toolkit as toolkit
from ckan import model
from ckan.common import g
from ckan.lib.dictization import model_dictize, model_save
from ckan.lib.navl.validators import not_empty
from ckan.logic import schema as ckan_schema, validate
from ckan.model import State
from ckan.types import Action, Context, DataDict
from ckan.types.logic import ActionResult

from ckanext.syndicate import utils
from ckanext.mailcraft.utils import get_mailer
from ckanext.mailcraft.exception import MailerException

import ckanext.datavic_iar_theme.helpers as theme_helpers
from ckanext.datavicmain import helpers
from ckanext.datavicmain.logic import schema as vic_schema

_check_access = toolkit.check_access
config = toolkit.config
log = logging.getLogger(__name__)
user_is_registering = helpers.user_is_registering
ValidationError = toolkit.ValidationError
get_action = toolkit.get_action
_validate = toolkit.navl_validate

CONFIG_SYNCHRONIZED_ORGANIZATION_FIELDS = (
    "ckanext.datavicmain.synchronized_organization_fields"
)
DEFAULT_SYNCHRONIZED_ORGANIZATION_FIELDS = ["name", "title", "description"]


def user_create(context, data_dict):
    model = context["model"]
    schema = context.get("schema") or ckan_schema.default_user_schema()
    # DATAVICIAR-42: Add unique email validation
    # unique email validation is their by default now in CKAN 2.9 email_is_unique
    # But they have removed not_empty so lets insert it back in
    schema["email"].insert(0, not_empty)
    session = context["session"]

    _check_access("user_create", context, data_dict)

    data, errors = _validate(data_dict, schema, context)

    if user_is_registering():
        # DATAVIC-221: If the user registers set the state to PENDING where a sysadmin can activate them
        data["state"] = State.PENDING

    create_org_member = False

    if user_is_registering():
        # DATAVIC-221: Validate the organisation_id
        organisation_id = data_dict.get("organisation_id", None)

        # DATAVIC-221: Ensure the user selected an orgnisation
        if not organisation_id:
            errors["organisation_id"] = ["Please select an Organisation"]
        # DATAVIC-221: Ensure the user selected a valid top-level organisation
        elif organisation_id not in theme_helpers.get_parent_orgs("list"):
            errors["organisation_id"] = ["Invalid Organisation selected"]
        else:
            create_org_member = True

    if errors:
        session.rollback()
        raise ValidationError(errors)

    # user schema prevents non-sysadmins from providing password_hash
    if "password_hash" in data:
        data["_password"] = data.pop("password_hash")

    user = model_save.user_dict_save(data, context)

    # Flush the session to cause user.id to be initialised, because
    # activity_create() (below) needs it.
    session.flush()

    activity_create_context = {
        "model": model,
        "user": context["user"],
        "defer_commit": True,
        "ignore_auth": True,
        "session": session,
    }
    activity_dict = {
        "user_id": user.id,
        "object_id": user.id,
        "activity_type": "new user",
    }
    get_action("activity_create")(activity_create_context, activity_dict)

    if user_is_registering() and create_org_member:
        # DATAVIC-221: Add the new (pending) user as a member of the organisation
        get_action("member_create")(
            activity_create_context,
            {
                "id": organisation_id,
                "object": user.id,
                "object_type": "user",
                "capacity": "member",
            },
        )

    if not context.get("defer_commit"):
        model.repo.commit()

    # A new context is required for dictizing the newly constructed user in
    # order that all the new user's data is returned, in particular, the
    # api_key.
    #
    # The context is copied so as not to clobber the caller's context dict.
    user_dictize_context = context.copy()
    user_dictize_context["keep_apikey"] = True
    user_dictize_context["keep_email"] = True
    user_dict = model_dictize.user_dictize(user, user_dictize_context)

    context["user_obj"] = user
    context["id"] = user.id

    model.Dashboard.get(user.id)  # Create dashboard for user.

    if user_is_registering():
        # DATAVIC-221: Send new account requested emails
        user_emails = [
            x.strip()
            for x in config.get(
                "ckan.datavic.request_access_review_emails", []
            ).split(",")
        ]
        helpers.send_email(
            user_emails,
            "new_account_requested",
            {
                "user_name": user.name,
                "user_url": toolkit.url_for(
                    "user.read", id=user.name, qualified=True
                ),
                "site_title": config.get("ckan.site_title"),
                "site_url": config.get("ckan.site_url"),
            },
        )

    log.debug("Created user {name}".format(name=user.name))
    return user_dict


@toolkit.chained_action
def organization_update(next_, context, data_dict):
    """Update remote organization if it's changed. We track only a subset of fields."""
    old_org: OrderedDict[str, Any] = (
        context["model"].Group.get(data_dict.get("id")).as_dict()
    )

    result = next_(context, data_dict)
    tracked_fields: list[str] = toolkit.aslist(
        toolkit.config.get(
            CONFIG_SYNCHRONIZED_ORGANIZATION_FIELDS,
            DEFAULT_SYNCHRONIZED_ORGANIZATION_FIELDS,
        )
    )

    if not _is_org_changed(old_org, result, tracked_fields):
        return result

    for profile in utils.get_profiles():
        ckan = utils.get_target(profile.ckan_url, profile.api_key)

        try:
            remote = ckan.action.organization_show(id=old_org["name"])
        except ckanapi.NotFound:
            continue

        ckan.action.organization_patch(
            id=remote["id"],
            **{f: result[f] for f in tracked_fields},
        )

    return result


def _is_org_changed(
    old_org: dict[str, Any], new_org: dict[str, Any], tracked_fields: list[str]
) -> bool:
    for field_name in tracked_fields:
        if old_org.get(field_name) != new_org.get(field_name):
            return True

    return False


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
