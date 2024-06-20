from __future__ import annotations

from typing import Any


def get_config_schema() -> dict[Any, Any] | None:
    from ckanext.scheming.plugins import _load_schemas, _expand_schemas

    schemas = _load_schemas(
        ["ckanext.datavicmain_home:config_schema.yaml"], "schema_id"
    )
    expanded_schemas = _expand_schemas(schemas)

    if schema := expanded_schemas.get("datavicmain_home_manage"):
        return schema
