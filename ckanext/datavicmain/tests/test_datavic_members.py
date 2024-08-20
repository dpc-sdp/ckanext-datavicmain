from __future__ import annotations

from ckan.views.feed import organization
from ckanext.files.model import owner
import py
import pytest

import ckan.plugins.toolkit as tk
import ckan.model as model
import ckan.tests.helpers as helpers

import ckanext.datavicmain.views.datavic_member as datavic_member


@pytest.mark.usefixtures(
    "reset_db_once",
    "with_plugins",
)
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


@pytest.mark.usefixtures(
    "reset_db_once",
    "with_plugins",
)
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


@pytest.mark.usefixtures(
    "reset_db_once",
    "with_plugins",
)
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


@pytest.mark.usefixtures(
    "reset_db_once",
    "with_plugins",
)
class TestReassignUserPackagesInOrganisation:
    def test_target_user_doesnt_exist(self, user, organization):
        with pytest.raises(tk.ObjectNotFound):
            datavic_member.reassign_user_packages(
                organization["id"], user["id"], "non-existent"
            )

    def test_user_has_no_packages(self, user_factory, organization_factory):
        user1 = user_factory()
        user2 = user_factory()

        organization = organization_factory(
            users=[{"name": user2["name"], "capacity": "editor"}]
        )
        result = datavic_member.reassign_user_packages(
            organization["id"], user1["id"], user2["id"]
        )

        assert result == []

    def test_user_has_packages(
        self, user_factory, package_factory, organization_factory
    ):
        user1 = user_factory()
        user2 = user_factory()
        organization = organization_factory(
            users=[{"name": user2["name"], "capacity": "editor"}]
        )
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


@pytest.mark.usefixtures(
    "reset_db_once", "with_plugins", "with_request_context"
)
class TestRemoveMemberView:
    def test_regular_user(self, app, user, organization):
        resp = app.post(
            url=tk.h.url_for("datavic_member.remove_member"),
            data={"org_id": organization["id"], "user_id": user["id"]},
            extra_environ={"Authorization": user["token"]},
        )

        assert resp.status_code == 403

    def test_sysadmin_user(self, app, sysadmin, user, organization_factory):
        organization = organization_factory(
            users=[
                {"name": user["name"], "capacity": "member"},
            ]
        )

        roles = tk.h.datavic_get_user_roles_in_org(
            user["id"], organization["id"]
        )

        assert roles

        resp = app.post(
            url=tk.h.url_for("datavic_member.remove_member"),
            data={"org_id": organization["id"], "user_id": user["id"]},
            extra_environ={"Authorization": sysadmin["token"]},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert not tk.h.datavic_get_user_roles_in_org(
            user["id"], organization["id"]
        )

    def test_remove_user_with_package_reassignment(
        self,
        app,
        sysadmin,
        user_factory,
        organization_factory,
        package_factory,
    ):
        user1 = user_factory()
        user2 = user_factory()
        organization = organization_factory(
            users=[
                {"name": user1["name"], "capacity": "editor"},
                {"name": user2["name"], "capacity": "admin"},
            ]
        )

        package_factory(user=user1, owner_org=organization["id"])

        resp = app.post(
            url=tk.h.url_for("datavic_member.remove_member"),
            data={
                "org_id": organization["id"],
                "user_id": user1["id"],
                "new_member": user2["id"],
            },
            extra_environ={"Authorization": sysadmin["token"]},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert not datavic_member.get_user_packages_for_organisation(
            org_id=organization["id"], user_id=user1["id"]
        )
        assert datavic_member.get_user_packages_for_organisation(
            org_id=organization["id"], user_id=user2["id"]
        )


@pytest.mark.usefixtures(
    "reset_db_once", "with_plugins", "with_request_context"
)
class TestRemoveUserView:
    def test_remove_user_without_packages(self, app, user, sysadmin):
        resp = app.post(
            url=tk.h.url_for("datavic_member.remove_user"),
            data={"user_id": user["id"]},
            extra_environ={"Authorization": sysadmin["token"]},
            follow_redirects=False,
        )

        assert resp.status_code == 302

        user = helpers.call_action("user_show", id=user["id"])

        assert user["state"] == model.State.DELETED

    def test_remove_user_with_packages(
        self, app, user, sysadmin, package_factory, organization_factory
    ):
        """We shouldn't be able to delete a user if some of their packages
        are not reassigned to another org member."""
        organization = organization_factory(
            users=[{"name": user["name"], "capacity": "editor"}]
        )
        package_factory(user=user, owner_org=organization["id"])

        resp = app.post(
            url=tk.h.url_for("datavic_member.remove_user"),
            data={"user_id": user["id"]},
            extra_environ={"Authorization": sysadmin["token"]},
            follow_redirects=False,
        )

        assert resp.status_code == 400

        user = helpers.call_action("user_show", id=user["id"])

        assert user["state"] == model.State.ACTIVE
