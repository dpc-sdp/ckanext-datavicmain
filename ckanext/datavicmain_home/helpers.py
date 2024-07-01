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

    return sorted(
        [
            item.dictize({})
            for item in HomeSectionItem.get_by_section(section_type)
            if item.state == HomeSectionItem.State.active
        ],
        key=lambda x: x["weight"],
    )


def vic_home_get_sections() -> list[str]:
    """Get all section types.

    Returns:
        list[str]: The section types.
    """

    return HomeSectionItem.get_all_section_types()
