from ckan.types import Schema

import ckan.plugins.toolkit as tk
import ckan.model as model
from ckan.logic import schema as ckan_schema


def custom_user_create_schema() -> Schema:
    schema = ckan_schema.user_new_form_schema()

    available_orgs = [org["value"] for org in tk.h.vic_iar_get_parent_orgs()]
    roles = [
        role["value"]
        for role in tk.h.datavic_get_registration_org_role_options()
    ]

    schema.update({
        "organisation_id": [
            tk.get_validator("not_empty"),
            tk.get_validator("unicode_safe"),
            tk.get_validator("one_of")(available_orgs),
        ],
        "organisation_role": [
            tk.get_validator("not_empty"),
            tk.get_validator("unicode_safe"),
            tk.get_validator("one_of")(roles),
        ],
        "state": [
            tk.get_validator("default")(model.State.PENDING),
            tk.get_validator("one_of")(model.State.PENDING),
        ],
    })

    return schema
