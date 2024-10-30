from __future__ import annotations

from typing import Callable, Any
import json

import ckan.plugins.toolkit as tk

from ckanext.transmute.types import Field

_transmutators: dict[str, Callable[..., Any]] = {}


def get_transmutators():
    return _transmutators


def transmutator(func):
    _transmutators[f"datavic_{func.__name__}"] = func
    return func


@transmutator
def restrict_res_formats(field: Field, fmts: list[str]) -> Field:
    resources = []
    formats: list[str] = [fmt.lower() for fmt in fmts]

    for res in field.value:
        if not res.get("format"):
            resources.append(res)
            continue

        if res["format"].lower() in formats:
            resources.append(res)

    field.value = resources
    return field


@transmutator
def to_json_string(field: Field) -> Field:
    """Casts field.value to json str

    Args:
        field (Field): Field object

    Returns:
        Field: the same Field with new value
    """
    try:
        field.value = json.dumps(field.value)
    except (ValueError, TypeError) as e:
        raise tk.Invalid(tk._('Invalid JSON object: {}').format(e))

    return field
