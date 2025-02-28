from __future__ import annotations

import logging
import mimetypes
from typing import Any, Optional

import requests

import ckan.authz as authz
import ckan.lib.navl.dictization_functions as df
import ckan.plugins.toolkit as tk
import ckan.types as types

log = logging.getLogger(__name__)


def datavic_tag_string(key, data, errors, context):
    request = (
        tk.request
        if repr(tk.request) != "<LocalProxy unbound>"
        and hasattr(tk.request, "args")
        else None
    )
    if request:
        end_point = tk.get_endpoint()
        if (
            end_point
            and end_point[0] in ["dataset", "datavic_dataset"]
            and end_point[1] in ["new", "edit"]
        ):
            tk.get_validator("not_empty")(key, data, errors, context)
            return

    tk.get_validator("ignore_missing")(key, data, errors, context)


def datavic_owner_org_validator(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """Altered owner_org_validator validator. We stripped out logic, that didn't
    allow us to change the organisation if you're a collaborator.
    """
    value = data.get(key)

    if value is tk.missing or value is None:
        if not authz.check_config_permission("create_unowned_dataset"):
            raise tk.Invalid(tk._("An organization must be provided"))
        data.pop(key, None)
        raise df.StopOnError

    user = context["model"].User.get(context["user"])
    package = context.get("package")

    if value == "":
        if not authz.check_config_permission("create_unowned_dataset"):
            raise tk.Invalid(tk._("An organization must be provided"))
        return

    group = context["model"].Group.get(value)
    if not group:
        raise tk.Invalid(tk._("Organization does not exist"))
    group_id = group.id

    if not package or (package and package.owner_org != group_id):
        # This is a new dataset or we are changing the organization
        if not context.get("ignore_auth", False) and (
            not user
            or not (
                user.sysadmin
                or authz.has_user_permission_for_group_or_org(
                    group_id, user.name, "create_dataset"
                )
            )
        ):
            raise tk.Invalid(
                tk._("You cannot add a dataset to this organization")
            )

    data[key] = group_id


def datavic_organization_upload(key, data, errors, context):
    """Process image upload or URL for an organization.

    HACK: we're adding an error under the `Logo` key, because client want to
    rename the field, but changing the field machine name will throw away uploaded
    previously files"""
    image_upload = tk.request.files.get("image_upload")
    errors[("Logo",)] = []

    if image_upload:
        mimetype = image_upload.mimetype
    else:
        image_url = data.get(("image_url",))
        if not image_url.startswith("http"):
            return
        if not image_url:
            return
        try:
            mimetype = _get_mimetype_from_url(image_url)
        except ValueError as e:
            errors[("Logo",)].append(str(e))
            return

    if not mimetype:
        return

    if not _is_valid_image_extension(mimetype):
        errors[("Logo",)].append(
            (
                "Image format is not supported. "
                "Select an image in one of the following formats: "
                "JPG, JPEG, GIF, PNG, WEBP."
            )
        )


def _is_valid_image_extension(mimetype: str) -> bool:
    """Check if the mimetype corresponds to a valid image extension."""
    valid_extensions = ["jpg", "png", "jpeg", "gif", "webp"]
    extension = mimetypes.guess_extension(mimetype)
    return extension and extension.strip(".").lower() in valid_extensions


def _get_mimetype_from_url(image_url: str) -> Optional[str]:
    """Attempt to get the mimetype of an image given its URL."""
    try:
        response = requests.head(image_url, allow_redirects=True, timeout=5)
        response.raise_for_status()
        return response.headers.get("Content-Type")
    except requests.RequestException as e:
        raise ValueError(f"Error fetching image: {e}")


def datavic_visibility_validator(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """
    Datasets owned by restricted organisations can only be made visible to
    members of the current organisation
    """
    value = data.get(key)
    owner_org = data.get(("owner_org",))
    is_restricted = tk.h.datavic_is_org_restricted(owner_org)
    if is_restricted and value != "current":
        errors[("organization_visibility",)].append(
            """Incorrect value - datasets owned by restricted
            organisations can only be made visible to members of the current
            organisation"""
        )
        return


def datavic_private_validator(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """
    Datasets owned by restricted organisations are not suitable for
    public release
    """
    value = data.get(key)
    owner_org = data.get(("owner_org",))
    is_restricted = tk.h.datavic_is_org_restricted(owner_org)
    if is_restricted and value is False:
        errors[("private",)].append(
            """Incorrect value - datasets owned by restricted organisations are
            not suitable for public release"""
        )
        return


def datavic_email_validator(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """
    Validate that the email address is not already in use. It might be either
    an existing user or a pending user.
    """
    model = context["model"]  # type: ignore
    existing_users = (
        model.Session.query(model.User)
        .filter(model.User.email.ilike(data[key]))
        .all()
    )

    for user in existing_users:
        if user and user.state in [model.State.ACTIVE, model.State.PENDING]:
            errors[("registration",)] = [
                "<strong>406 Registration unsuccessful.</strong> Please email <a href='mailto:datavic@dpc.vic.gov.au'>datavic@dpc.vic.gov.au</a> for assistance"
            ]
        return


def datavic_organization_parent_validator(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """
    Restricted organization can't be assigned as a child of unrestricted one
    or vice versa
    """
    value = data.get(("groups", 0, "name"))
    visibility = data.get(("visibility",)) == "restricted"
    model = context["model"]
    parent = model.Group.get(value)
    if parent:
        is_restricted = tk.h.datavic_is_org_restricted(parent.id)
        if (is_restricted and not visibility) or (
            not is_restricted and visibility
        ):
            errors[("parent",)].append(
                """Incorrect value - restricted organization can't be assigned
                as a child of unrestricted one or vice versa"""
            )
            return


def datavic_set_org_visibility_if_new(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """
    The field can be set at creation stage only
    """
    blueprint, endpoint = tk.get_endpoint()
    if blueprint == "organization" and endpoint == "edit":
        model = context["model"]
        old_value = model.Group.get(data[("name",)]).extras.get("visibility")
        new_value = data[key]
        if old_value != new_value:
            errors[key].append(
                """Incorrect value - the field can be set at creation stage only"""
            )
            return


def datavic_filesize_validator(
    key: types.FlattenKey,
    data: types.FlattenDataDict,
    errors: types.FlattenErrorDict,
    context: types.Context,
) -> Any:
    """
    Check if the field value is an integer
    """
    value = data.get(key)

    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            errors[key].append(
                "Enter file size in bytes (numeric values only), or leave blank"
            )
            return
