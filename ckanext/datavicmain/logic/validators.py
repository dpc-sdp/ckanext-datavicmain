from __future__ import annotations

from typing import Any
import logging

import ckan.types as types
import ckan.authz as authz
import ckan.plugins.toolkit as toolkit
import ckan.lib.navl.dictization_functions as df

log = logging.getLogger(__name__)


def datavic_tag_string(key, data, errors, context):
    request = (
        toolkit.request
        if repr(toolkit.request) != "<LocalProxy unbound>"
        and hasattr(toolkit.request, "args")
        else None
    )
    if request:
        end_point = toolkit.get_endpoint()
        if (
            end_point
            and end_point[0] in ["dataset", "datavic_dataset"]
            and end_point[1] in ["new", "edit"]
        ):
            toolkit.get_validator("not_empty")(key, data, errors, context)
            return

    toolkit.get_validator("ignore_missing")(key, data, errors, context)


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

    if value is toolkit.missing or value is None:
        if not authz.check_config_permission("create_unowned_dataset"):
            raise toolkit.Invalid(
                toolkit._("An organization must be provided")
            )
        data.pop(key, None)
        raise df.StopOnError

    user = context["model"].User.get(context["user"])
    package = context.get("package")

    if value == "":
        if not authz.check_config_permission("create_unowned_dataset"):
            raise toolkit.Invalid(
                toolkit._("An organization must be provided")
            )
        return

    group = context["model"].Group.get(value)
    if not group:
        raise toolkit.Invalid(toolkit._("Organization does not exist"))
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
            raise toolkit.Invalid(
                toolkit._("You cannot add a dataset to this organization")
            )

    data[key] = group_id
