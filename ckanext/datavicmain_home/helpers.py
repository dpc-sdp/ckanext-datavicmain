from __future__ import annotations

from typing import Any

from ckanext.datavicmain_home.model import HomeSectionItem


def get_item_by_section_type(section_type: str) -> list[dict[str, Any]]:
    """Get item by type.

    Args:
        item_type (str): The item type to get items for.

    Returns:
        list[dict[str, Any]]: The section items.
    """

    return [
        item.dictize({})
        for item in HomeSectionItem.get_by_section(section_type)
        if item.state == HomeSectionItem.State.active
    ]
