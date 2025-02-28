from __future__ import annotations

import base64
import json
import logging
import math
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import ckan.authz as authz
import ckan.model as model
import ckan.plugins.toolkit as toolkit

from ckanext.activity.model.activity import Activity
from ckanext.harvest.model import HarvestObject

from ckanext.datavicmain.config import get_dtv_external_link, get_dtv_url

from . import config as conf
from . import const, utils

log = logging.getLogger(__name__)
WORKFLOW_STATUS_OPTIONS = [
    "draft",
    "ready_for_approval",
    "published",
    "archived",
]

CONFIG_REGISTRATION_ENDPOINTS = "ckanext.datavicmain.registration_endpoints"
DEFAULT_REGISTRATION_ENDPOINTS = ["user.register", "datavicuser.register"]

CONFIG_DTV_FQ = "ckanext.datavicmain.dtv.supported_formats"
DEFAULT_DTV_FQ = [
    "wms",
    "shapefile",
    "zip (shp)",
    "shp",
    "kmz",
    "geojson",
    "csv-geo-au",
    "aus-geo-csv",
]

# Conditionally import the the workflow extension helpers if workflow extension enabled in .ini
if "workflow" in toolkit.config.get("ckan.plugins", False):
    from ckanext.workflow import helpers as workflow_helpers

    workflow_enabled = True


def add_package_to_group(pkg_dict, context):
    group_id = pkg_dict.get("category", None)
    if group_id:
        group = model.Group.get(group_id)
        groups = context.get("package").get_groups("group")
        if group not in groups:
            group.add_package_by_name(pkg_dict.get("name"))


def set_data_owner(owner_org):
    data_owner = ""
    if owner_org:
        organization = model.Group.get(owner_org)
        if organization:
            parents = organization.get_parent_group_hierarchy("organization")
            if parents:
                data_owner = parents[0].title
            else:
                data_owner = organization.title
    return data_owner.strip()


def is_dataset_harvested(package_id):
    if not package_id:
        return None

    harvested = model.Session.query(
        model.Session.query(HarvestObject)
        .filter_by(package_id=package_id)
        .filter_by(state="COMPLETE")
        .exists()
    ).scalar()

    return harvested


def is_user_account_pending_review(user_id):
    # get_action('user_show') does not return the 'reset_key' so the only way to get this field is from the User model
    user = model.User.get(user_id)
    return user and user.is_pending() and user.reset_key is None


def set_private_activity(pkg_dict, context, activity_type):
    pkg = model.Package.get(pkg_dict["id"])
    user = context["user"]
    session = context["session"]
    user_obj = model.User.by_name(user)

    if user_obj:
        user_id = user_obj.id
    else:
        user_id = str("not logged in")

    activity = Activity.activity_stream_item(pkg, activity_type, user_id)
    session.add(activity)
    return pkg_dict


def user_is_registering():
    return toolkit.get_endpoint() == ("datavicuser", "register")


def dataset_fields(dataset_type="dataset"):
    schema = toolkit.h.scheming_get_dataset_schema(dataset_type)
    return schema.get("dataset_fields", [])


def resource_fields(dataset_type="dataset"):
    schema = toolkit.h.scheming_get_dataset_schema(dataset_type)
    return schema.get("resource_fields", [])


def field_choices(field_name):
    field = toolkit.h.scheming_field_by_name(dataset_fields(), field_name)
    return toolkit.h.scheming_field_choices(field)


def option_value_to_label(field_name, value):
    choices = field_choices(field_name)
    label = toolkit.h.scheming_choices_label(choices, value)

    return label


def group_list(self):
    group_list = []
    for group in model.Group.all("group"):
        group_list.append({"value": group.id, "label": group.title})
    return group_list


def workflow_status_options(
    current_workflow_status: str, owner_org: str, package_id: str
) -> list[dict[str, Any]]:

    options = []

    if "workflow" in toolkit.config.get("ckan.plugins", False):
        user = toolkit.g.userobj
        is_collaborator_editor = authz.user_is_collaborator_on_dataset(
            user.id, package_id, "editor"
        )
        is_org_admin = (
            authz.users_role_for_group_or_org(owner_org, user.name) == "admin"
        )

        if is_collaborator_editor and not is_org_admin:
            settings = workflow_helpers.load_workflow_settings()
            workflow_options = (
                workflow_helpers.get_workflow_status_options_for_role(
                    settings["roles"], "editor"
                )
            )
        else:
            workflow_options = (
                workflow_helpers.get_available_workflow_statuses(
                    current_workflow_status, owner_org, user.name
                )
            )

        for option in workflow_options:
            options.append(
                {
                    "value": option,
                    "text": option.replace("_", " ").capitalize(),
                }
            )

        return options
    else:
        return [{"value": "draft", "text": "Draft"}]


def autoselect_workflow_status_option(current_workflow_status):
    selected_option = "draft"
    user = toolkit.g.user
    if authz.is_sysadmin(user):
        selected_option = current_workflow_status
    return selected_option


def workflow_status_pretty(workflow_status):
    return workflow_status.replace("_", " ").capitalize()


def get_organisations_allowed_to_upload_resources():
    orgs = toolkit.config.get(
        "ckan.organisations_allowed_to_upload_resources",
        ["victorian-state-budget"],
    )
    return orgs


def get_user_organizations(username):
    user = model.User.get(username)
    return user.get_groups("organization")


def user_org_can_upload(pkg_id):
    user = toolkit.g.user
    org_name = None

    if pkg_id is None:
        request_path = urlsplit(toolkit.request.url)
        if request_path.path is not None:
            fragments = request_path.path.split("/")
            if fragments[1] == "dataset":
                pkg_id = fragments[2]

    if pkg_id is not None:
        dataset = toolkit.get_action("package_show")(
            {"user": user}, {"name_or_id": pkg_id}
        )
        org_name = dataset.get("organization").get("name")

    if toolkit.h.datavic_org_uploads_allowed(org_name) and (
        authz.users_role_for_group_or_org(org_name, user)
        in ["editor", "admin"]
    ):
        return True

    allowed_organisations = get_organisations_allowed_to_upload_resources()
    user_orgs = get_user_organizations(user)
    for org in user_orgs:
        if org.name in allowed_organisations and org.name == org_name:
            return True
    return False


def is_ready_for_publish(pkg):
    workflow_publish = pkg.get("workflow_status")
    is_private = pkg.get("private")

    if not is_private and workflow_publish == "published":
        return True
    return False


def get_digital_twin_resources(pkg_id: str) -> list[dict[str, Any]]:
    """Select resource suitable for DTV(Digital Twin Visualization).

    Additional info:
    https://gist.github.com/steve9164/b9781b517c99486624c02fdc7af0f186
    """
    supported_formats = {
        fmt.lower()
        for fmt in toolkit.aslist(
            toolkit.config.get(CONFIG_DTV_FQ, DEFAULT_DTV_FQ)
        )
    }

    try:
        pkg = toolkit.get_action("package_show")(
            {"ignore_auth": True}, {"id": pkg_id}
        )
    except (toolkit.ObjectNotFound, toolkit.NotAuthorized):
        return []

    # Additional info #2
    if pkg["state"] != "active":
        return []

    acceptable_resources = {}
    for res in pkg["resources"]:
        if not res["format"]:
            continue

        fmt = res["format"].lower()
        # Additional info #1
        if fmt not in supported_formats:
            continue

        # Additional info #3
        if (
            fmt in {"kml", "kmz", "shp", "shapefile", "zip (shp)"}
            and len(pkg["resources"]) > 1
        ):
            continue

        # Additional info #3
        if fmt == "wms" and ~res["url"].find("data.gov.au/geoserver"):
            continue

        # Additional info #4
        if res["name"] in acceptable_resources:
            if acceptable_resources[res["name"]]["created"] > res["created"]:
                continue

        acceptable_resources[res["name"]] = res

    return list(acceptable_resources.values())


def url_for_dtv_config(ids: list[str], embedded: bool = True) -> str:
    """Build URL where DigitalTwin can get map configuration for the preview.

    It uses ODP base URL because DigitalTwin doesn't have access to IAR. As
    result, non-syndicated datasets cannot be visualized.

    """
    base_url: str = (
        toolkit.config.get("ckanext.datavicmain.odp.public_url")
        or toolkit.config["ckan.site_url"]
    )

    encoded = base64.urlsafe_b64encode(bytes(json.dumps(ids), "utf8"))
    return urljoin(
        base_url,
        toolkit.url_for(
            "datavicmain.dtv_config", encoded=encoded, embedded=embedded
        ),
    )


def datavic_org_uploads_allowed(org_id: str) -> bool:
    org = model.Group.get(org_id)
    if not org:
        return False

    try:
        flake = toolkit.get_action("flakes_flake_lookup")(
            {"ignore_auth": True},
            {
                "author_id": None,
                "name": utils.org_uploads_flake_name(),
            },
        )
    except toolkit.ObjectNotFound:
        return False

    return flake["data"].get(org.id, False)


def get_group(
    group: Optional[str] = None, include_datasets: bool = False
) -> dict[str, Any]:
    if group is None:
        return {}
    try:
        return toolkit.get_action("group_show")(
            {}, {"id": group, "include_datasets": include_datasets}
        )
    except (toolkit.NotFound, toolkit.ValidationError, toolkit.NotAuthorized):
        return {}


def dtv_exceeds_max_size_limit(resource_id: str) -> bool:
    """Check if DTV resource exceeds the maximum file size limit

    Args:
        resource_id (str): DTV resource id

    Returns:
        bool: return True if dtv resource exceeds maximum file size limit set
            in ckan config "ckanext.datavicmain.dtv.max_size_limit",
            otherwise - False
    """
    try:
        resource = toolkit.get_action("resource_show")({}, {"id": resource_id})
    except (toolkit.ObjectNotFound, toolkit.NotAuthorized):
        return True

    limit = conf.get_dtv_max_size_limit()
    filesize = resource.get("filesize")
    if filesize and int(filesize) >= int(limit):
        return True

    return False


def datavic_get_org_roles() -> list[str]:
    return ["admin", "editor", "member"]


def datavic_user_is_a_member_of_org(user_id: str, org_id: str) -> bool:
    if not user_id:
        return False

    user_orgs = get_user_organizations(user_id)

    for org in user_orgs:
        if org.id == org_id:
            return True

    return False


def datavic_get_user_roles_in_org(user_id: str, org_id: str) -> list[str]:
    user = model.User.get(user_id)

    if not user:
        return []

    user_orgs = user.get_groups("organization")
    role = None

    for organization in user_orgs:
        if org_id not in [organization.id, organization.name]:
            continue

        members = organization.member_all

        for member in members:
            if member.table_name != "user":
                continue

            if member.table_id == user.id:
                role = member.capacity

    if not role:
        return []

    return {
        "admin": ["admin", "editor", "member"],
        "editor": ["editor", "member"],
        "member": ["member"],
    }[role]


def datavic_is_pending_request_to_join_org(username: str, org_id: str) -> bool:
    requests = utils.get_pending_org_access_requests()

    for req in requests:
        if req["name"] == username and req["organisation_id"] == org_id:
            return True

    return False


def datavic_org_has_unrestricted_child(org_id: str) -> bool:
    """Check if the organization has restricted children orgs"""
    organization = model.Group.get(org_id)

    if not organization:
        return False

    child_orgs = organization.get_children_group_hierarchy("organization")

    if not child_orgs:
        return False

    for child_org in child_orgs:
        org_object = model.Group.get(child_org[0])

        if not org_object:
            continue

        if (
            org_object.extras.get(
                const.ORG_VISIBILITY_FIELD, const.ORG_UNRESTRICTED
            )
            == const.ORG_UNRESTRICTED
        ):
            return True

    return False


def datavic_org_has_restricted_parents(org_id: str) -> bool:
    """Check if the organization has restricted children orgs"""
    organization = model.Group.get(org_id)

    if not organization:
        return False

    parent_orgs = organization.get_parent_group_hierarchy("organization")

    if not parent_orgs:
        return False

    for parent_org in parent_orgs:
        if (
            parent_org.extras.get(const.ORG_VISIBILITY_FIELD)
            == const.ORG_RESTRICTED
        ):
            return True

    return False


def datavic_is_org_restricted(org_id: str) -> bool:
    """Check if the organization is .is_org_restricted(org_id)"""
    return utils.is_org_restricted(org_id)


def datavic_restrict_hierarchy_tree(
    hierarchy_tree: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove restricted orgs from a hierarchy tree if user has no access to them

    Tree example:
    [
        {
            "children": [
                {
                    "children": [
                        {
                            "id": "86ebc3fe-bca5-4c8b-aba7-75f716b5ef82",
                            ...
                        }
                    ],
                    "id": "f8e43010-b5d4-4bed-9102-31f3279e776c",
                    ...
                }
            ],
            "id": "e2b76bda-8d6b-4a1c-b098-b1bc8dc6c361",
            ...
        },
        {
            "children": [],
            "id": "59e96e8e-93ac-4970-a040-339114322e7d",
            ...
        },
    ]
    """

    result = []

    for org_dict in hierarchy_tree:
        if not utils.user_has_org_access(
            org_dict["id"], toolkit.current_user.name
        ):
            continue

        org_dict["children"] = datavic_restrict_hierarchy_tree(
            org_dict["children"]
        )

        result.append(org_dict)

    return result


@toolkit.chained_helper
def group_tree_parents(next_func, id_, type_="organization"):
    """Update group_tree_parents to exclude restricted organisation from the
    tree"""
    return _group_tree_parents(id_, type_)


def _group_tree_parents(id_, type_="organization"):
    try:
        tree_node = toolkit.get_action("organization_show")({}, {"id": id_})
    except toolkit.ObjectNotFound:
        return []

    if tree_node["groups"]:
        parent_id = tree_node["groups"][0]["name"]

        try:
            parent_node = toolkit.get_action("organization_show")(
                {}, {"id": parent_id}
            )
        except toolkit.ObjectNotFound:
            return []

        return _group_tree_parents(parent_id) + [parent_node]
    else:
        return []


def add_current_organisation(
    available_organisations: list[dict[str, Any]], current_org: dict[str, Any]
):
    """When user doesn't have an access to an organisation, it won't be included
    for a list of available organisations. Include it there, but check if it's
    not already there"""

    current_org_included = False

    for organization in available_organisations:
        if organization["id"] == current_org["id"]:
            current_org_included = True
            break

    if not current_org_included:
        available_organisations.append(current_org)

    return available_organisations


def datavic_max_image_size():
    """Return max size for image configuration for portal"""
    return toolkit.config["ckan.max_image_size"]


def datavic_get_dtv_url(ext_link: bool = False) -> str:
    """Return a URL for DTV map preview"""
    if toolkit.asbool(ext_link):
        url = get_dtv_external_link()
    else:
        url = get_dtv_url()

    if not url:
        return url

    if not url.endswith("/"):
        url = url + "/"

    return url


def has_user_capacity(
    org_id: str, current_user_id: str, capacity: Optional[str] = None
) -> bool:
    """Check if the current user has an appropriate capacity in the certain organization

    Args:
        org_id (str): the id or name of the organization
        current_user_id (str): the id or name of the user
        capacity (str): restrict the members returned to those with a given capacity,
                        e.g. 'member', 'editor', 'admin', 'public', 'private'
                        (optional, default: None)

    Returns:
        bool: True for success, False otherwise
    """
    try:
        members = toolkit.get_action("member_list")(
            {}, {"id": org_id, "object_type": "user", "capacity": capacity}
        )
        members_id = [member[0] for member in members]
        if current_user_id in members_id:
            return True
    except (toolkit.ObjectNotFound, toolkit.NotAuthorized):
        return False

    return False


def localized_filesize(size_bytes: Any) -> str:
    """Returns a localized unicode representation of a number in bytes, MB
    etc.

    It's  similar  to  CKAN's  original `localised_filesize`,  but  uses  MB/KB
    instead of MiB/KiB.  Additionally, it rounds up to 1.0KB  any value that is
    smaller than 1000.
    """

    if isinstance(size_bytes, str) and not size_bytes.isdecimal():
        return size_bytes

    size_bytes = int(size_bytes)

    if size_bytes < 1:
        return ""

    size_name = ("bytes", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(float(size_bytes) / p, 1)

    return f"{s} {size_name[i]}"


def datavic_get_org_members(org_id: str) -> list[dict[str, Any]]:
    """Get organization members"""
    return toolkit.get_action("member_list")(
        {"user": toolkit.current_user.name},
        {"id": org_id, "object_type": "user"},
    )


def datavic_update_org_error_dict(
    error_dict: dict[str, Any],
) -> dict[str, Any]:
    """Internal CKAN logic makes a validation for resource file size. We want
    to show it as an error on the Logo field."""
    if error_dict.pop("upload", "") == ["File upload too large"]:
        error_dict["Logo"] = [
            f"File size is too large. Select an image which is no larger than {datavic_max_image_size()}MB."
        ]
    elif "Unsupported upload type" in error_dict.pop("image_upload", [""])[0]:
        error_dict["Logo"] = [
            (
                "Image format is not supported. "
                "Select an image in one of the following formats: "
                "JPG, JPEG, GIF, PNG, WEBP."
            )
        ]

    return error_dict


def datavic_allowable_parent_orgs(org_id: str = None) -> list[dict[str, Any]]:
    all_orgs = toolkit.h.get_allowable_parent_groups(org_id)
    user_id = toolkit.current_user.id
    orgs = []
    for org in all_orgs:
        if datavic_is_org_restricted(
            org.id
        ) and not datavic_user_is_a_member_of_org(user_id, org.id):
            continue
        orgs.append(org)
    return orgs
