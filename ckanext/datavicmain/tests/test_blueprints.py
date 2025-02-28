from __future__ import annotations

from unittest import mock

import pytest

import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.plugins.toolkit import url_for
from ckan.tests.helpers import call_action

import ckanext.datavicmain.utils as vic_utils


@pytest.mark.usefixtures("clean_db", "with_plugins")
class TestDatavicUserEndpoints:
    def test_user_approve(self, app, user, sysadmin):
        app.get(
            url_for("datavicuser.approve", user_id=user["id"]),
            headers={"Authorization": sysadmin["token"]},
            status=302,
            follow_redirects=False,
        )

        assert (
            call_action("user_show", id=user["id"])["state"]
            == model.State.ACTIVE
        )

    def test_user_approve_not_authorized(self, app, user):

        response = app.get(
            url_for("datavicuser.approve", user_id=user["id"]),
            headers={"Authorization": user["token"]},
            status=403,
        )

        assert "Unauthorized to activate user" in response

    def test_user_deny(self, app, sysadmin, user):
        app.get(
            url_for("datavicuser.deny", id=user["id"]),
            headers={"Authorization": sysadmin["token"]},
        )

        assert (
            call_action("user_show", id=user["id"])["state"]
            == model.State.DELETED
        )

    def test_user_deny_not_authorized(self, app, user):
        url = url_for("datavicuser.deny", id=user["id"])
        env = {"Authorization": user["token"]}

        response = app.get(url=url, headers=env, status=403)

        assert "Unauthorized to reject user" in response


@pytest.mark.usefixtures("clean_db", "with_plugins")
class TestDatavicUserUpdate:
    def test_regular_user_update_wrong_old(self, app, user):
        response = app.post(
            url=url_for("datavicuser.edit"),
            headers={"Authorization": user["token"]},
            status=200,
            data={
                "save": "",
                "email": user["email"],
                "name": user["name"],
                "old_password": "wrong-old-pass",
                "password1": "123",
                "password2": "123",
            },
            follow_redirects=False,
        )

        assert "Old Password: incorrect password" in response

    def test_regular_user_update_proper_old(self, app, user):
        app.post(
            url=url_for("datavicuser.edit"),
            headers={"Authorization": user["token"]},
            status=302,
            data={
                "save": "",
                "email": user["email"],
                "name": user["name"],
                "old_password": "correct123",
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
            follow_redirects=False,
        )

    def test_sysadmin_do_not_need_old_for_other_users(
        self, app, user, sysadmin
    ):
        app.post(
            url=url_for("datavicuser.edit", id=user["name"]),
            headers={"Authorization": sysadmin["token"]},
            data={
                "save": "",
                "email": user["email"],
                "name": user["name"],
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
            follow_redirects=False,
        )

    def test_sysadmin_need_old_for_themselves(self, app, sysadmin):
        response = app.post(
            url=url_for("datavicuser.edit", id=sysadmin["name"]),
            headers={"Authorization": sysadmin["token"]},
            data={
                "save": "",
                "email": sysadmin["email"],
                "name": sysadmin["name"],
                "old_password": "wrong-old-pass",
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
            follow_redirects=False,
        )
        assert "Old Password: incorrect password" in response

    def test_sysadmin_update_with_old_pass(self, app, sysadmin):
        app.post(
            url=url_for("datavicuser.edit", id=sysadmin["name"]),
            headers={"Authorization": sysadmin["token"]},
            data={
                "save": "",
                "email": sysadmin["email"],
                "name": sysadmin["name"],
                "old_password": "correct123",
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
            follow_redirects=False,
        )

    def test_user_update_with_null_password(self, user):
        user["password"] = None

        with pytest.raises(tk.ValidationError):
            call_action("user_update", **user)

    def test_user_update_with_invalid_password(self, user):
        for password in (False, -1, 23, 30.7):
            user["password"] = password

            with pytest.raises(tk.ValidationError):
                call_action("user_update", **user)


@pytest.mark.usefixtures("clean_db", "with_plugins")
@pytest.mark.ckan_config(
    "ckan.datavic.request_access_review_emails", "test@gmail.com"
)
@mock.patch("ckanext.datavicmain.utils.notify_about_pending_user")
class TestDatavicUserCreate:
    """We are not creating an active user on registration. Instead, the user
    will be in a pending state. Sysadmin could approve or deny the user later
    """

    def test_user_create_no_org_selected(self, send_email_notification, app):
        response = app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_1",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
            },
        )

        send_email_notification.assert_not_called()

        assert "Missing value" in response.body

    def test_user_create_member(
        self, send_email_notification, app, organization
    ):
        app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_1",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "member",
            },
        )

        send_email_notification.assert_called()

        user_dict = call_action("user_show", id="test_user_1")
        assert user_dict["state"] == model.State.PENDING

        joined_org = call_action(
            "organization_list_for_user", id=user_dict["id"]
        )[0]

        assert joined_org
        assert joined_org["capacity"] == "member"

    def test_user_create_editor(
        self, send_email_notification, app, organization, sysadmin
    ):
        """If user requests to be an editor, we are making him a member first
        after the approval. Then a join request as an editor will be created
        for an organisation admin to approve"""
        app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_1",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "editor",
            },
        )

        send_email_notification.assert_called()

        user_dict = call_action("user_show", id="test_user_1")
        assert user_dict["state"] == model.State.PENDING

        joined_org = call_action(
            "organization_list_for_user", id=user_dict["id"]
        )[0]

        assert joined_org
        assert joined_org["capacity"] == "member"

        assert vic_utils.UserPendingEditorFlake.get_pending_users()[
            user_dict["id"]
        ]

        app.get(
            url=url_for("datavicuser.approve", user_id=user_dict["id"]),
            headers={"Authorization": sysadmin["token"]},
            status=302,
            follow_redirects=False,
        )

        assert (
            vic_utils.get_pending_org_access_requests()[0]["name"]
            == user_dict["name"]
        )

    def test_cant_register_with_same_email_while_pending(
        self, send_email_notification, app, organization
    ):
        app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_1",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "editor",
            },
        )

        user_dict = call_action("user_show", id="test_user_1")
        assert user_dict["state"] == model.State.PENDING

        response = app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_2",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "editor",
            },
        )

        assert "Registration unsuccessful" in response

        with pytest.raises(tk.ObjectNotFound):
            call_action("user_show", id="test_user_2")

    def test_email_is_case_insensetive(
        self, send_email_notification, app, organization
    ):
        app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_1",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "editor",
            },
        )

        user_dict = call_action("user_show", id="test_user_1")
        assert user_dict["state"] == model.State.PENDING

        response = app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_2",
                "email": "Test_User_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "editor",
            },
        )

        assert "Registration unsuccessful" in response


@pytest.mark.usefixtures("clean_db", "with_plugins")
@mock.patch("ckanext.datavicmain.utils.notify_about_org_join_request")
class TestDatavicOrgRequestJoin:
    """Test that user is able to request to join into the org"""

    def test_join(self, send_email_notification, app, user, organization):
        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            headers={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        pending_request = vic_utils.get_pending_org_access_requests()[0]

        assert isinstance(pending_request, dict)
        assert pending_request["name"] == user["name"]
        assert pending_request["organisation_id"] == organization["name"]
        assert pending_request["organisation_role"] == "member"

    def test_join_twice(
        self, send_email_notification, app, user, organization
    ):
        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            headers={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            headers={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        pending_requests = vic_utils.get_pending_org_access_requests()
        assert len(pending_requests) == 1

        pending_request = pending_requests[0]
        assert isinstance(pending_request, dict)
        assert pending_request["name"] == user["name"]
        assert pending_request["organisation_id"] == organization["name"]
        assert pending_request["organisation_role"] == "member"

    def test_join_if_already_member(
        self, send_email_notification, app, user, organization
    ):
        call_action(
            "member_create",
            id=organization["id"],
            object=user["id"],
            object_type="user",
            capacity="editor",
        )

        resp = app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["id"],
            ),
            headers={"Authorization": user["token"]},
            data={"organisation_role": "member"},
        )

        send_email_notification.assert_not_called()

        assert not vic_utils.get_pending_org_access_requests()
        assert (
            "You already have a member role in this organization" in resp.body
        )

    def test_join_member_if_already_an_editor(
        self, send_email_notification, app, user, organization
    ):
        call_action(
            "member_create",
            id=organization["id"],
            object=user["id"],
            object_type="user",
            capacity="editor",
        )

        resp = app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["id"],
            ),
            headers={"Authorization": user["token"]},
            data={"organisation_role": "member"},
        )

        send_email_notification.assert_not_called()

        assert not vic_utils.get_pending_org_access_requests()
        assert (
            "You already have a member role in this organization" in resp.body
        )


@pytest.mark.usefixtures("clean_db", "with_plugins")
class TestDatavicOrgRequestList:
    def test_regular_user(self, app, user, organization):
        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            headers={"Authorization": user["token"]},
        )

        assert resp.status_code == 403

    def test_sysadmin(self, app, sysadmin, organization):
        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            headers={"Authorization": sysadmin["token"]},
        )

        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "role, status_code",
        [("admin", 200), ("editor", 403), ("member", 403)],
    )
    def test_roles_access(self, role, status_code, app, user, organization):
        call_action(
            "member_create",
            id=organization["id"],
            object=user["id"],
            object_type="user",
            capacity=role,
        )

        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            headers={"Authorization": user["token"]},
        )

        assert resp.status_code == status_code

    def test_empty_list(self, app, sysadmin, organization):
        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            headers={"Authorization": sysadmin["token"]},
        )

        assert "No pending access requests" in resp.body

    @mock.patch("ckanext.datavicmain.utils.notify_about_org_join_request")
    def test_with_request(
        self, send_email_notification, app, user, sysadmin, organization
    ):
        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            headers={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            headers={"Authorization": sysadmin["token"]},
        )

        assert "No pending access requests" not in resp.body
        assert "Reject" in resp.body
        assert "Approve" in resp.body
