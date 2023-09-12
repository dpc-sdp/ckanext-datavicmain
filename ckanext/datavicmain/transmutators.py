from __future__ import annotations

from typing import Callable, Any


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
