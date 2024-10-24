import pytest

import ckan.plugins.toolkit as tk


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestGetHomeSections:
    def test_no_items(self):
        assert not tk.h.vic_home_get_sections()

    def test_one_item(self, home_section_item_factory):
        home_section_item = home_section_item_factory(section_type="test")
        assert tk.h.vic_home_get_sections() == [
            home_section_item["section_type"]
        ]

    def test_reoder(self, home_section_item_factory):
        home_section_item_factory(section_type="test")
        home_section_item_factory(section_type="test 2", weight="-1")

        assert tk.h.vic_home_get_sections() == ["test 2", "test"]


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestGetSectionItemsBySectionType:
    def test_no_items(self):
        assert not tk.h.get_item_by_section_type("test")

    def test_one_item(self, home_section_item_factory):
        home_section_item = home_section_item_factory(section_type="test")

        assert tk.h.get_item_by_section_type("test") == [home_section_item]

    def test_two_items(self, home_section_item_factory):
        home_section_item_factory(section_type="test")
        home_section_item_factory(section_type="test")

        assert len(tk.h.get_item_by_section_type("test")) == 2

    def test_two_items_different_section(self, home_section_item_factory):
        home_section_item_factory(section_type="test")
        home_section_item_factory(section_type="test 2")

        assert len(tk.h.get_item_by_section_type("test 2")) == 1
        assert len(tk.h.get_item_by_section_type("test")) == 1
