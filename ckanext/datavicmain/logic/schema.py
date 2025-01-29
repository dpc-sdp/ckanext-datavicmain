from __future__ import annotations

from typing import Any
from ckan.types import Schema

import ckan.plugins.toolkit as tk
import ckan.model as model
from ckan.logic.schema import validator_args
from ckan.logic import schema as ckan_schema


def custom_user_create_schema() -> Schema:
    schema = ckan_schema.user_new_form_schema()

    available_orgs = [org["value"] for org in tk.h.vic_iar_get_parent_orgs()]

    schema.update({
        "organisation_id": [
            tk.get_validator("not_empty"),
            tk.get_validator("unicode_safe"),
            tk.get_validator("one_of")(available_orgs),
        ],
        "organisation_role": [
            tk.get_validator("not_empty"),
            tk.get_validator("unicode_safe"),
            tk.get_validator("one_of")(tk.h.datavic_get_org_roles()),
        ],
        "state": [
            tk.get_validator("default")(model.State.PENDING),
            tk.get_validator("one_of")(model.State.PENDING),
        ],
    }) # type: ignore

    schema["email"].append(tk.get_validator("datavic_email_validator"))

    return schema


@validator_args
def delwp_data_request_schema(
    not_missing, unicode_safe, email_validator, package_id_or_name_exists
) -> dict[str, list[Any]]:
    return {
        "username": [not_missing, unicode_safe],
        "email": [not_missing, unicode_safe, email_validator],
        "organisation": [not_missing, unicode_safe],
        "message": [not_missing, unicode_safe],
        "package_id": [not_missing, unicode_safe, package_id_or_name_exists],
    }


@validator_args
def datatables_view_prioritize(not_empty):
    return {
        "resource_id": [
            not_empty,
        ],
    }
