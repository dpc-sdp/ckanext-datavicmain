from __future__ import annotations

from typing import Any


def get_config_schema() -> dict[Any, Any]:
    from ckanext.scheming.plugins import _expand_schemas, _load_schemas

    schemas = _load_schemas(
        ["ckanext.datavicmain_home:config_schema.yaml"], "schema_id"
    )
    expanded_schemas = _expand_schemas(schemas)

    return expanded_schemas["datavicmain_home_item"]
