from __future__ import annotations

from ckanext.files.model import owner
import py
import pytest

import ckan.plugins.toolkit as tk
import ckan.model as model
import ckan.tests.helpers as helpers

import ckanext.datavicmain.views.datavic_member as datavic_member


@pytest.mark.usefixtures("reset_db_once")
class TestGetUserPackagesForOrganisation:
    def test_user_is_not_a_member_of_organisation(self, user, organization):
        result = datavic_member.get_user_packages_for_organisation(
            organization["id"], user["id"]
        )

        assert result == []

    def test_user_is_a_member_of_organisation(
        self, user, organization_factory, package_factory
    ):
        organization = organization_factory(
            users=[{"name": user["name"], "capacity": "member"}]
        )

        dataset = package_factory(owner_org=organization["id"], user=user)

        result = datavic_member.get_user_packages_for_organisation(
            organization["id"], user["id"]
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], model.Package)
        assert result[0].id == dataset["id"]

    def test_organisation_has_other_packages(
        self, user, user_factory, organization_factory, package_factory
    ):
        organization = organization_factory(
            users=[{"name": user["name"], "capacity": "member"}]
        )

        user2 = user_factory()
        package_factory(owner_org=organization["id"], user=user2)
        dataset = package_factory(owner_org=organization["id"], user=user)

        result = datavic_member.get_user_packages_for_organisation(
            organization["id"], user["id"]
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], model.Package)
        assert result[0].id == dataset["id"]


@pytest.mark.usefixtures("reset_db_once")
class TestGetUserPackages:
    def test_user_has_no_packages(self, user):
        result = datavic_member.get_user_packages(user["id"])

        assert result == []

    def test_user_has_packages(self, user, package_factory):
        package_factory(user=user)

        result = datavic_member.get_user_packages(user["id"])

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], model.Package)


@pytest.mark.usefixtures("reset_db_once")
class TestGetOrganisationEditorsAndAdmins:
    def test_organisation_does_not_exist(self):
        result = datavic_member.get_organisation_editors_and_admins(
            "non-existent"
        )

        assert result == []

    def test_organisation_has_no_members(self, organization_factory):
        organization = organization_factory(users=[])
        result = datavic_member.get_organisation_editors_and_admins(
            organization["id"],
        )

        # there will be extra admin user created within organisation_create action
        assert len(result) == 1

        helpers.call_action(
            "member_delete",
            object=result[0]["user"].id,
            id=organization["id"],
            object_type="user",
            capacity="member",
        )

        assert not datavic_member.get_organisation_editors_and_admins(
            organization["id"],
        )

    def test_organisation_has_members(
        self, organization_factory, user_factory
    ):
        user1 = user_factory()
        user2 = user_factory()
        user3 = user_factory()

        organization = organization_factory(
            users=[
                {"name": user1["name"], "capacity": "member"},
                {"name": user2["name"], "capacity": "editor"},
                {"name": user3["name"], "capacity": "admin"},
            ]
        )

        result = datavic_member.get_organisation_editors_and_admins(
            organization["id"]
        )

        assert isinstance(result, list)
        # there will be extra admin user created within organisation_create action
        assert len(result) == 3

        for member in result:
            assert member["role"] != "member"

    def test_delete_user(self, organization_factory):
        organization = organization_factory(users=[])
        result = datavic_member.get_organisation_editors_and_admins(
            organization["id"],
        )

        # there will be extra admin user created within organisation_create action
        assert len(result) == 1

        helpers.call_action("user_delete", id=result[0]["user"].id)

        assert not datavic_member.get_organisation_editors_and_admins(
            organization["id"],
        )


@pytest.mark.usefixtures("reset_db_once")
class TestReassignUserPackagesInOrganisation:
    def test_target_user_doesnt_exist(self, user, organization):
        with pytest.raises(tk.ObjectNotFound):
            datavic_member.reassign_user_packages(
                organization["id"], user["id"], "non-existent"
            )

    def test_user_has_no_packages(self, user_factory, organization):
        user1 = user_factory()
        user2 = user_factory()

        result = datavic_member.reassign_user_packages(
            organization["id"], user1["id"], user2["id"]
        )

        assert result == []

    def test_user_has_packages(
        self, user_factory, package_factory, organization
    ):
        user1 = user_factory()
        user2 = user_factory()
        package = package_factory(user=user1, owner_org=organization["id"])

        result = datavic_member.reassign_user_packages(
            organization["id"], user1["id"], user2["id"]
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], model.Package)
        assert result[0].id == package["id"]
        assert result[0].creator_user_id == user2["id"]

    def test_target_user_is_not_active(
        self, user_factory, package_factory, organization
    ):
        user1 = user_factory()
        user2 = user_factory(state=model.State.DELETED)
        package_factory(user=user1, owner_org=organization["id"])

        with pytest.raises(
            tk.ValidationError, match="Target user is not active"
        ):
            datavic_member.reassign_user_packages(
                organization["id"], user1["id"], user2["id"]
            )

    def test_target_user_is_not_an_editor_or_admin_of_org(
        self, user_factory, package_factory, organization
    ):
        user1 = user_factory()
        user2 = user_factory()
        package_factory(user=user1, owner_org=organization["id"])

        with pytest.raises(
            tk.ValidationError,
            match="Target user is not an editor or admin of the organization",
        ):
            datavic_member.reassign_user_packages(
                organization["id"], user1["id"], user2["id"]
            )
