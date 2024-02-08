from __future__ import annotations

import pytest
from unittest import mock

import ckan.tests.helpers as helpers

from ckanext.datavicmain import const


@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestOrganisationListRestricted(object):
    def test_no_resticted_orgs(self, user, organization):
        results = helpers.call_action(
            "organization_list",
            context={"user": user["name"]},
            data_dict={"all_fields": True},
        )

        assert results

        results = helpers.call_action(
            "organization_list",
            context={"user": user["name"]},
        )

        assert results

    def test_resticted_for_regular_user(self, user, organization_factory):
        organization_factory(
            **{const.ORG_VISIBILITY_FIELD: const.ORG_RESTRICTED}
        )

        results = helpers.call_action(
            "organization_list",
            context={"user": user["name"]},
            data_dict={"all_fields": True},
        )

        assert not results

        results = helpers.call_action(
            "organization_list",
            context={"user": user["name"]},
        )

        assert not results


    def test_not_resticted_for_sysadmins(self, sysadmin, organization_factory):
        organization_factory(
            **{const.ORG_VISIBILITY_FIELD: const.ORG_RESTRICTED}
        )

        results = helpers.call_action(
            "organization_list",
            context={"user": sysadmin["name"]},
            data_dict={"all_fields": True},
        )

        assert results

        results = helpers.call_action(
            "organization_list",
            context={"user": sysadmin["name"]},
        )

        assert results

@pytest.mark.usefixtures("with_plugins", "clean_db")
class TestOrganisationUpdate(object):
    @mock.patch("ckanext.datavicmain.logic.action.notify_about_org_join_request")
    def test_reindex_not_triggered(self, reindex_job, organization):
        pass
