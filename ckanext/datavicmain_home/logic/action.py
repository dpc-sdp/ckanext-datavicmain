from __future__ import annotations

import datetime
from typing import Any

import ckan.types as types
import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.logic import validate

from ckanext.datavicmain_home.model import HomeSectionItem
from ckanext.datavicmain_home.logic import schema


@validate(schema.create_section_item)
def create_section_item(
    context: types.Context, data_dict: types.DataDict
) -> dict[str, Any]:
    """Create a new section item.

    Args:
        data_dict (dict): The data for the new section item.

    Returns:
        dict[str, Any]: The created section item.
    """
    tk.check_access("manage_home_sections", context, data_dict)

    if "upload" in data_dict:
        upload = data_dict.pop("upload")

        result = tk.get_action("files_file_create")(context, {"upload": upload})
        data_dict["image_id"] = result["id"]

    item = HomeSectionItem(**data_dict)

    model.Session.add(item)
    model.Session.commit()

    return item.dictize(None)


@validate(schema.delete_section_item)
def delete_section_item(
    context: types.Context, data_dict: types.DataDict
) -> None:
    """Delete a section item.

    Args:
        item_id (str): The id of the section item to delete.
    """
    tk.check_access("manage_home_sections", context, data_dict)

    item = HomeSectionItem.get(data_dict["id"])

    if not item:
        return

    if item.image_id:
        try:
            tk.get_action("files_file_delete")(context, {"id": item.image_id})
        except (tk.ValidationError, tk.ObjectNotFound):
            pass

    item.delete()
    model.Session.commit()


@validate(schema.update_section_item)
def update_section_item(
    context: types.Context, data_dict: types.DataDict
) -> dict[str, Any]:
    """Update a section item.

    Args:
        item_id (str): The id of the section item to update.
        data_dict (dict): The data to update the section item with.

    Raises:
        tk.ValidationError: If the section item is not found.

    Returns:
        dict[str, Any]: The updated section item.
    """
    tk.check_access("manage_home_sections", context, data_dict)

    item = HomeSectionItem.get(data_dict["id"])

    if not item:
        raise tk.ValidationError("Section item not found")

    if "upload" in data_dict:
        if item.image_id:
            try:
                tk.get_action("files_file_delete")(context, {"id": item.image_id})
            except (tk.ValidationError, tk.ObjectNotFound):
                pass

        upload = data_dict.pop("upload")

        result = tk.get_action("files_file_create")(context, {"upload": upload})
        data_dict["image_id"] = result["id"]

    for key, value in data_dict.items():
        setattr(item, key, value)

    item.modified_at = datetime.datetime.utcnow()

    model.Session.commit()

    return item.dictize({})


@tk.side_effect_free
@validate(schema.get_section_items_by_section_type)
def get_section_items_by_section_type(
    context: types.Context, data_dict: types.DataDict
) -> list[dict[str, Any]]:
    """Get section items by section type.

    Args:
        section_type (str): The section type to get items for.

    Returns:
        list[dict[str, Any]]: The section items.
    """
    tk.check_access("get_home_sections", context, data_dict)

    items = HomeSectionItem.get_by_section(data_dict["section_type"])

    return [item.dictize({}) for item in items]

@tk.side_effect_free
def get_all_section_items(
    context: types.Context, data_dict: types.DataDict
) -> list[dict[str, Any]]:
    """Get all section items.

    Returns:
        list[dict[str, Any]]: The section items.
    """
    tk.check_access("get_home_sections", context, data_dict)

    items = HomeSectionItem.all()

    return [item.dictize({}) for item in items]


@tk.side_effect_free
def get_section_item(context: types.Context, data_dict: types.DataDict) -> dict[str, Any]:
    """Get a section item.

    Args:
        item_id (str): The id of the section item to get.

    Returns:
        dict[str, Any]: The section item.
    """
    tk.check_access("get_home_sections", context, data_dict)

    item = HomeSectionItem.get(data_dict["id"])

    if not item:
        raise tk.ObjectNotFound("Section item not found")

    return item.dictize({})


def vic_home_remove_item_image(context, data_dict):
    tk.check_access("manage_home_sections", context, data_dict)

    image_id: str = tk.get_or_bust(tk.request.form, "item_id")

    item = HomeSectionItem.get(image_id)

    if not item or not item.image_id:
        return {"success": True}

    try:
        tk.get_action("files_file_delete")({}, {"id": item.image_id})
    except (tk.ValidationError, tk.ObjectNotFound):
        pass
    else:
        item.image_id = None
        model.Session.commit()

    return {"success": True}
