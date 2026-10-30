import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from conftest import PASSWORD

LOGIN_URL = reverse("accounts:login")


def login(client, username, password=PASSWORD, **extra):
    return client.post(LOGIN_URL, {"username": username, "password": password, **extra})


def is_logged_in(client):
    return "_auth_user_id" in client.session


@pytest.mark.django_db
def test_login_page_renders_with_csrf_token(client):
    response = client.get(LOGIN_URL)
    assert response.status_code == 200
    assert b"csrfmiddlewaretoken" in response.content


def test_valid_login_lands_on_role_dashboard(client, coordinator):
    response = login(client, "coordinator")
    assert response.status_code == 302
    assert is_logged_in(client)
    response = client.get(response.url, follow=True)
    assert response.redirect_chain[-1][0] == reverse("core:coordinator_dashboard")


def test_wrong_password_is_rejected(client, caller):
    response = login(client, "caller", "wrong-password")
    assert response.status_code == 200
    assert not is_logged_in(client)
    assert response.context["form"].non_field_errors()


def test_inactive_user_cannot_log_in(client, make_user):
    make_user("inactive", is_active=False)
    login(client, "inactive")
    assert not is_logged_in(client)


def test_login_requires_csrf_token(caller):
    csrf_client = Client(enforce_csrf_checks=True)
    response = login(csrf_client, "caller")
    assert response.status_code == 403
    assert not is_logged_in(csrf_client)


def test_login_ignores_external_next_url(client, caller):
    response = login(client, "caller", next="https://evil.example/phish")
    assert response.status_code == 302
    assert response.url == reverse(settings.LOGIN_REDIRECT_URL)


def test_logged_in_user_visiting_login_is_redirected(client, caller):
    client.force_login(caller)
    assert client.get(LOGIN_URL).status_code == 302


def test_logout_requires_post(client, caller):
    client.force_login(caller)
    assert client.get(reverse("accounts:logout")).status_code == 405
    assert is_logged_in(client)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert not is_logged_in(client)


def test_repeated_failures_lock_out_even_correct_password(client, caller):
    for _ in range(settings.AXES_FAILURE_LIMIT):
        login(client, "caller", "wrong-password")
    response = login(client, "caller")
    assert response.status_code == 429
    assert b"Too many login attempts" in response.content
    assert not is_logged_in(client)


def test_password_change(client, caller):
    client.force_login(caller)
    response = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": PASSWORD,
            "new_password1": "Another-synthetic-9",
            "new_password2": "Another-synthetic-9",
        },
    )
    assert response.status_code == 302
    caller.refresh_from_db()
    assert caller.check_password("Another-synthetic-9")


def test_password_change_rejects_short_password(client, caller):
    client.force_login(caller)
    response = client.post(
        reverse("accounts:password_change"),
        {"old_password": PASSWORD, "new_password1": "short1", "new_password2": "short1"},
    )
    assert response.status_code == 200
    caller.refresh_from_db()
    assert caller.check_password(PASSWORD)
