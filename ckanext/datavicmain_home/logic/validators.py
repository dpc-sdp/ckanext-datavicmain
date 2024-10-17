from __future__ import annotations

import ckan.plugins.toolkit as tk

from ckanext.datavicmain_home.model import HomeSectionItem


def home_section_item_exists(item_id: str, context) -> str:
    """Ensures that the home section item exists."""

    result = HomeSectionItem.get(item_id)

    if not result:
        raise tk.Invalid(f"Home section item {item_id} not found")

    return item_id
