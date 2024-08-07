from __future__ import annotations

from typing import Any, Optional
import logging
import mimetypes

import ckan.types as types
import ckan.authz as authz
import ckan.lib.navl.dictization_functions as df
import ckan.plugins.toolkit as tk
import requests

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
            raise tk.Invalid(
                tk._("An organization must be provided")
            )
        data.pop(key, None)
        raise df.StopOnError

    user = context["model"].User.get(context["user"])
    package = context.get("package")

    if value == "":
        if not authz.check_config_permission("create_unowned_dataset"):
            raise tk.Invalid(
                tk._("An organization must be provided")
            )
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
                "JPG, JPEG, GIF, PNG, BMP, SVG."
            )
        )
    

def _is_valid_image_extension(mimetype: str) -> bool:
    """Check if the mimetype corresponds to a valid image extension."""
    valid_extensions = ["jpg", "png", "jpeg", "gif", "bmp", "svg"]
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
