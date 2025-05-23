from __future__ import annotations

from typing import Any, Callable

import pytest
from playwright.sync_api import Page, expect

import ckan.plugins.toolkit as tk


@pytest.mark.playwright
@pytest.mark.usefixtures("with_plugins", "clean_db", "clean_index")
class TestDatasetSearch:
    def test_public_dataset(
        self, page: Page, package_factory: Callable[..., dict[str, Any]]
    ):
        dataset = package_factory(private=False)

        page.goto(tk.h.url_for("dataset.search"))
        expect(page.locator(".privacy-label ")).to_have_text(
            "Open to the public"
        )

        page.get_by_role("link", name=dataset["title"]).click()

        expect(page).to_have_url(
            tk.h.url_for("dataset.read", id=dataset["name"])
        )

    def test_private_dataset(
        self, page: Page, package_factory: Callable[..., dict[str, Any]]
    ):

        dataset = package_factory(private=True)

        page.goto(tk.h.url_for("dataset.search"))

        expect(page).not_to_have_url(
            tk.h.url_for("dataset.read", id=dataset["name"])
        )

    def test_private_dataset_badge(
        self,
        page: Page,
        package_factory: Callable[..., dict[str, Any]],
        sysadmin: dict[str, Any],
    ):
        package_factory(private=True, workflow_status="published")

        page.context.set_extra_http_headers(
            {"Authorization": sysadmin["token"]}
        )
        page.goto(tk.h.url_for("dataset.search"))

        expect(page.locator(".privacy-label")).to_have_text("Open to VPS only")
