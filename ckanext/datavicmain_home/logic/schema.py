from __future__ import annotations

from typing import Any, Dict

from ckan.logic.schema import validator_args

from ckanext.datavicmain_home.model import HomeSectionItem

Schema = Dict[str, Any]


@validator_args
def create_section_item(
    not_empty,
    default,
    ignore_missing,
    unicode_safe,
    one_of,
    ignore,
    url_validator,
) -> Schema:
    return {
        "title": [not_empty, unicode_safe],
        "description": [ignore_missing, unicode_safe],
        "image_id": [ignore_missing, unicode_safe],
        "url": [ignore_missing, url_validator],
        "state": [
            default(HomeSectionItem.State.active),
            one_of(
                [HomeSectionItem.State.active, HomeSectionItem.State.inactive]
            ),
        ],
        "section_type": [
            default(HomeSectionItem.SectionType.news),
            one_of(
                [
                    HomeSectionItem.SectionType.news,
                    HomeSectionItem.SectionType.data,
                    HomeSectionItem.SectionType.resources,
                ]
            ),
        ],
        "__extras": [ignore],
    }


@validator_args
def delete_section_item(
    not_empty, unicode_safe, ignore, home_section_item_exists
) -> Schema:
    return {
        "id": [not_empty, unicode_safe, home_section_item_exists],
        "__extras": [ignore],
    }


@validator_args
def update_section_item(
    not_empty,
    ignore_missing,
    unicode_safe,
    one_of,
    ignore,
    default,
    url_validator,
    home_section_item_exists,
) -> Schema:
    return {
        "id": [not_empty, unicode_safe, home_section_item_exists],
        "title": [ignore_missing, unicode_safe],
        "description": [ignore_missing, unicode_safe],
        "image_id": [ignore_missing, unicode_safe],
        "url": [ignore_missing, url_validator],
        "state": [
            default(HomeSectionItem.State.active),
            one_of(
                [HomeSectionItem.State.active, HomeSectionItem.State.inactive]
            ),
        ],
        "section_type": [
            default(HomeSectionItem.SectionType.news),
            one_of(
                [
                    HomeSectionItem.SectionType.news,
                    HomeSectionItem.SectionType.data,
                    HomeSectionItem.SectionType.resources,
                ]
            ),
        ],
        "__extras": [ignore],
    }


@validator_args
def get_section_items_by_section_type(
    not_empty,
    one_of,
    ignore,
) -> Schema:
    return {
        "section_type": [
            not_empty,
            one_of(
                [
                    HomeSectionItem.SectionType.news,
                    HomeSectionItem.SectionType.data,
                    HomeSectionItem.SectionType.resources,
                ]
            ),
        ],
        "__extras": [ignore],
    }
