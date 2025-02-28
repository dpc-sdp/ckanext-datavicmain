from __future__ import annotations

from typing import Any

import ckanapi
import pytest

from ckan.tests.helpers import call_action


@pytest.fixture
def ckan(user, app, monkeypatch):
    from ckanext.datavicmain.logic import action

    ckan = ckanapi.TestAppCKAN(app, user["apikey"])
    monkeypatch.setattr(action, "get_target", lambda *args: ckan)
    yield ckan


@pytest.mark.usefixtures("clean_db")
@pytest.mark.ckan_config("ckanext.syndicate.profile.odp.api_key", "xxx")
@pytest.mark.ckan_config("ckanext.syndicate.profile.odp.author", "xxx")
@pytest.mark.ckan_config(
    "ckanext.syndicate.profile.odp.refresh_package_name", "true"
)
@pytest.mark.ckan_config("ckanext.syndicate.profile.odp.organization", "None")
@pytest.mark.ckan_config("ckanext.syndicate.profile.odp.ckan_url", "xxx")
@pytest.mark.ckan_config(
    "ckanext.syndicate.profile.odp.replicate_organization", "true"
)
class TestOrgSyndication:
    def test_sync_organization_name_changed(
        self, ckan, user: dict[str, Any], organization: dict[str, Any], mocker
    ):
        ckan.action.organization_show = mocker.Mock()
        ckan.action.organization_show.return_value = {"id": "xxx"}
        ckan.action.organization_patch = mocker.Mock()
        ckan.action.organization_patch.return_value = {
            "id": organization["id"]
        }

        call_action(
            "organization_patch",
            id=organization["id"],
            name="new-name",
            context={
                "user": user["name"],
            },
        )

        ckan.action.organization_patch.assert_called_once()

    def test_sync_organization_name_not_changed(
        self, ckan, user: dict[str, Any], organization: dict[str, Any], mocker
    ):
        ckan.action.organization_show = mocker.Mock()
        ckan.action.organization_show.return_value = {"id": "xxx"}
        ckan.action.organization_patch = mocker.Mock()

        call_action(
            "organization_patch",
            id=organization["id"],
            name=organization["name"],
            context={
                "user": user["name"],
            },
        )

        ckan.action.organization_patch.assert_not_called()

    def test_sync_organization_title_changed(
        self, ckan, user: dict[str, Any], organization: dict[str, Any], mocker
    ):
        ckan.action.organization_show = mocker.Mock()
        ckan.action.organization_show.return_value = {"id": "xxx"}
        ckan.action.organization_patch = mocker.Mock()
        ckan.action.organization_patch.return_value = {
            "id": organization["id"]
        }

        call_action(
            "organization_patch",
            id=organization["id"],
            title="new-title",
            context={
                "user": user["name"],
            },
        )

        ckan.action.organization_patch.assert_called_once()
