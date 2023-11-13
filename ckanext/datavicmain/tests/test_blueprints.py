import pytest

from ckan.plugins.toolkit import url_for


@pytest.mark.usefixtures('clean_db', 'with_plugins', "with_request_context")
class TestDatavicUserEndpoints:

    def test_user_approve(self, app, user, sysadmin):
        url = url_for('datavicuser.approve', id= user['id'])
        env = {"Authorization": sysadmin["token"]}

        response = app.get(url=url, extra_environ=env, status=200)

        assert 'User approved' in response

    def test_user_approve_not_authorized(self, app, user):
        url = url_for('datavicuser.approve', id= user['id'])
        env = {"Authorization": user["token"]}

        response = app.get(url=url, extra_environ=env, status=403)

        assert 'Unauthorized to activate user' in response

    def test_user_deny(self, app, sysadmin, user):
        url = url_for('datavicuser.deny', id= user['id'])
        env = {"Authorization": sysadmin["token"]}

        response = app.get(url=url, extra_environ=env, status=200)

        assert 'User Denied' in response


    def test_user_deny_not_authorized(self, app, user):
        url = url_for('datavicuser.deny', id= user['id'])
        env = {"Authorization": user["token"]}

        response = app.get(url=url, extra_environ=env, status=403)

        assert 'Unauthorized to reject user' in response
