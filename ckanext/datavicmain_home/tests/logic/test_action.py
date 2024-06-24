from __future__ import annotations

from typing import TypedDict

import pytest

import ckan.plugins.toolkit as tk
from ckan.tests.helpers import call_action

from ckanext.datavicmain_home.model import HomeSectionItem


class HomeSectionData(TypedDict):
    id: str
    title: str
    description: str
    image_id: str
    url: str
    state: str
    section_type: str


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestHomeSectionItemCreate:
    def test_basic_create(self, home_section_item_factory):
        home_section_item: HomeSectionData = home_section_item_factory()

        assert home_section_item["id"]
        assert home_section_item["title"]
        assert home_section_item["description"]
        assert home_section_item["image_id"]
        assert home_section_item["url"]
        assert home_section_item["state"] == HomeSectionItem.State.active
        assert (
            home_section_item["section_type"]
            == HomeSectionItem.SectionType.news
        )

    def test_create_with_invalid_url(self, home_section_item_factory):
        with pytest.raises(tk.ValidationError):
            home_section_item_factory(url="invalid-url")

    def test_create_with_invalid_state(self, home_section_item_factory):
        with pytest.raises(tk.ValidationError):
            home_section_item_factory(state="invalid-state")

    def test_create_with_invalid_section_type(self, home_section_item_factory):
        with pytest.raises(tk.ValidationError):
            home_section_item_factory(section_type="invalid-section-type")

    def test_create_without_title(self, home_section_item_factory):
        with pytest.raises(tk.ValidationError):
            home_section_item_factory(title="")

    def test_create_without_description(self, home_section_item_factory):
        home_section_item = home_section_item_factory(description="")

        assert home_section_item["description"] == ""


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestHomeSectionItemDelete:
    def test_basic_delete(self, home_section_item_factory):
        home_section_item: HomeSectionData = home_section_item_factory()

        call_action("delete_section_item", id=home_section_item["id"])

        result = call_action(
            "get_section_items_by_section_type",
            section_type=HomeSectionItem.SectionType.news,
        )

        assert not result

    def test_delete_with_invalid_id(self):
        with pytest.raises(tk.ValidationError):
            call_action("delete_section_item", id="invalid-id")


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestHomeSectionItemUpdate:
    def test_basic_update(self, home_section_item_factory):
        home_section_item: HomeSectionData = home_section_item_factory()

        new_title = "New title"
        new_description = "New description"
        new_image_id = "new-image-id"
        new_url = "https://example.com"
        new_state = HomeSectionItem.State.inactive
        new_section_type = HomeSectionItem.SectionType.data

        result = call_action(
            "update_section_item",
            id=home_section_item["id"],
            title=new_title,
            description=new_description,
            image_id=new_image_id,
            url=new_url,
            state=new_state,
            section_type=new_section_type,
        )

        assert result["title"] == new_title
        assert result["description"] == new_description
        assert result["image_id"] == new_image_id
        assert result["url"] == new_url
        assert result["state"] == new_state
        assert result["section_type"] == new_section_type

    def test_update_with_invalid_url(self, home_section_item_factory):
        home_section_item = home_section_item_factory()

        with pytest.raises(tk.ValidationError):
            call_action(
                "update_section_item",
                id=home_section_item["id"],
                url="invalid-url",
            )

    def test_update_with_invalid_state(self, home_section_item_factory):
        home_section_item = home_section_item_factory()

        with pytest.raises(tk.ValidationError):
            call_action(
                "update_section_item",
                id=home_section_item["id"],
                state="invalid-state",
            )

    def test_update_with_invalid_section_type(self, home_section_item_factory):
        home_section_item = home_section_item_factory()

        with pytest.raises(tk.ValidationError):
            call_action(
                "update_section_item",
                id=home_section_item["id"],
                section_type="invalid-section-type",
            )

    def test_update_without_title(self, home_section_item_factory):
        home_section_item = home_section_item_factory()

        result = call_action(
            "update_section_item",
            id=home_section_item["id"],
            title="",
        )

        assert result["title"] == ""

    def test_update_without_description(self, home_section_item_factory):
        home_section_item = home_section_item_factory()

        result = call_action(
            "update_section_item",
            id=home_section_item["id"],
            description="",
        )

        assert result["description"] == ""


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestGetItemsBySectionType:
    def test_get_items_by_section_type(self, home_section_item_factory):
        home_section_item: HomeSectionData = home_section_item_factory()

        result = call_action(
            "get_section_items_by_section_type",
            section_type=HomeSectionItem.SectionType.news,
        )

        assert result[0]["id"] == home_section_item["id"]

    def test_get_items_by_invalid_section_type(self):
        with pytest.raises(tk.ValidationError):
            call_action(
                "get_section_items_by_section_type",
                section_type="invalid-section-type",
            )

    def test_no_items(self):
        result = call_action(
            "get_section_items_by_section_type",
            section_type=HomeSectionItem.SectionType.news,
        )

        assert not result


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestGetAllItems:
    def test_get_all_items(self, home_section_item_factory):
        home_section_item: HomeSectionData = home_section_item_factory()

        result = call_action("get_all_section_items")

        assert result[0]["id"] == home_section_item["id"]

    def test_no_items(self):
        result = call_action("get_all_section_items")

        assert not result
