from __future__ import annotations

import pytest
from unittest import mock

import ckan.plugins.toolkit as tk
import ckan.model as model
from ckan.tests.helpers import call_action
from ckan.plugins.toolkit import url_for


from ckanext.datavicmain.utils import get_pending_org_access_requests


@pytest.mark.usefixtures("clean_db", "with_plugins", "with_request_context")
class TestDatavicUserEndpoints:
    def test_user_approve(self, app, user, sysadmin):
        url = url_for("datavicuser.approve", id=user["id"])
        env = {"Authorization": sysadmin["token"]}

        response = app.get(url=url, extra_environ=env, status=200)

        assert "User approved" in response

    def test_user_approve_not_authorized(self, app, user):
        url = url_for("datavicuser.approve", id=user["id"])
        env = {"Authorization": user["token"]}

        response = app.get(url=url, extra_environ=env, status=403)

        assert "Unauthorized to activate user" in response

    def test_user_deny(self, app, sysadmin, user):
        url = url_for("datavicuser.deny", id=user["id"])
        env = {"Authorization": sysadmin["token"]}

        response = app.get(url=url, extra_environ=env, status=200)

        assert "User Denied" in response

    def test_user_deny_not_authorized(self, app, user):
        url = url_for("datavicuser.deny", id=user["id"])
        env = {"Authorization": user["token"]}

        response = app.get(url=url, extra_environ=env, status=403)

        assert "Unauthorized to reject user" in response


@pytest.mark.usefixtures("clean_db", "with_plugins", "with_request_context")
class TestDatavicUserUpdate:
    def test_regular_user_update_wrong_old(self, app, user):
        response = app.post(
            url=url_for("datavicuser.edit"),
            extra_environ={"Authorization": user["token"]},
            status=200,
            data={
                "save": "",
                "email": user["email"],
                "name": user["name"],
                "old_password": "wrong-old-pass",
                "password1": "123",
                "password2": "123",
            },
        )

        assert "Old Password: incorrect password" in response

    def test_regular_user_update_proper_old(self, app, user):
        response = app.post(
            url=url_for("datavicuser.edit"),
            extra_environ={"Authorization": user["token"]},
            status=200,
            data={
                "save": "",
                "email": user["email"],
                "name": user["name"],
                "old_password": "correct123",
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
        )

        assert "Profile updated" in response

    def test_sysadmin_do_not_need_old_for_other_users(
        self, app, user, sysadmin
    ):
        response = app.post(
            url=url_for("datavicuser.edit", id=user["name"]),
            extra_environ={"Authorization": sysadmin["token"]},
            data={
                "save": "",
                "email": user["email"],
                "name": user["name"],
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
        )
        assert "Profile updated" in response

    def test_sysadmin_need_old_for_themselves(self, app, sysadmin):
        response = app.post(
            url=url_for("datavicuser.edit", id=sysadmin["name"]),
            extra_environ={"Authorization": sysadmin["token"]},
            data={
                "save": "",
                "email": sysadmin["email"],
                "name": sysadmin["name"],
                "old_password": "wrong-old-pass",
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
        )
        assert "Old Password: incorrect password" in response

    def test_sysadmin_update_with_old_pass(self, app, sysadmin):
        response = app.post(
            url=url_for("datavicuser.edit", id=sysadmin["name"]),
            extra_environ={"Authorization": sysadmin["token"]},
            data={
                "save": "",
                "email": sysadmin["email"],
                "name": sysadmin["name"],
                "old_password": "correct123",
                "password1": "new-pass-123",
                "password2": "new-pass-123",
            },
        )
        assert "Profile updated" in response

    def test_user_update_with_null_password(self, user):
        user["password"] = None

        with pytest.raises(tk.ValidationError):
            call_action("user_update", **user)

    def test_user_update_with_invalid_password(self, user):
        for password in (False, -1, 23, 30.7):
            user["password"] = password

            with pytest.raises(tk.ValidationError):
                call_action("user_update", **user)


@pytest.mark.usefixtures("clean_db", "with_plugins", "with_request_context")
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

        send_email_notification.assert_called()

        user_dict = call_action("user_show", id="test_user_1")
        assert user_dict["state"] == model.State.PENDING

        joined_org = call_action(
            "organization_list_for_user", id=user_dict["id"]
        )[0]

        assert joined_org
        assert joined_org["capacity"] == "editor"

    def test_user_create_not_sure(
        self, send_email_notification, app, organization
    ):
        """If user is not sure about role, we are making him a member..."""
        app.post(
            url_for("datavicuser.register"),
            data={
                "save": "",
                "name": "test_user_1",
                "email": "test_user_1@gmail.com",
                "password1": "TestPassword1",
                "password2": "TestPassword1",
                "organisation_id": organization["name"],
                "organisation_role": "not-sure",
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


@pytest.mark.usefixtures("clean_db", "with_plugins", "with_request_context")
@mock.patch("ckanext.datavicmain.utils.notify_about_org_join_request")
class TestDatavicOrgRequestJoin:
    """Test that user is able to request to join into the org"""

    def test_join(self, send_email_notification, app, user, organization):
        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        pending_request = get_pending_org_access_requests()[0]

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
            extra_environ={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        pending_requests = get_pending_org_access_requests()
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
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": user["token"]},
            data={"organisation_role": "member"},
        )

        send_email_notification.assert_not_called()

        assert not get_pending_org_access_requests()
        assert "You are already a member of this organisation" in resp.body


@pytest.mark.usefixtures("clean_db", "with_plugins", "with_request_context")
class TestDatavicOrgRequestList:
    def test_regular_user(self, app, user, organization):
        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": user["token"]},
        )

        assert resp.status_code == 403

    def test_sysadmin(self, app, sysadmin, organization):
        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": sysadmin["token"]},
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
            extra_environ={"Authorization": user["token"]},
        )

        assert resp.status_code == status_code

    def test_empty_list(self, app, sysadmin, organization):
        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": sysadmin["token"]},
        )

        assert "No pending access requests" in resp.body

    @mock.patch("ckanext.datavicmain.utils.notify_about_org_join_request")
    def test_with_request(self, send_email_notification, app, user, sysadmin, organization):
        app.post(
            url_for(
                "datavic_org.request_join",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": user["token"]},
            data={"organisation_role": "member"},
            follow_redirects=False,
        )

        resp = app.get(
            url_for(
                "datavic_org.request_list",
                org_id=organization["name"],
            ),
            extra_environ={"Authorization": sysadmin["token"]},
        )

        assert "No pending access requests" not in resp.body
        assert "Reject" in resp.body
        assert "Approve" in resp.body
