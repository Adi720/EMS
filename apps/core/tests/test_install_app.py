"""The site can be installed on a phone like an app."""

import json

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_manifest_is_public_and_complete(client):
    response = client.get(reverse("core:manifest"))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    data = json.loads(response.content)
    assert data["display"] == "standalone" and data["start_url"] == "/"
    assert data["name"] == "EMS Seva"
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon["purpose"] == "maskable" for icon in data["icons"])


@pytest.mark.parametrize("name", ["icon-192.png", "icon-512.png", "maskable-512.png", "apple-touch-icon.png"])
def test_icons_exist(name):
    assert finders.find(f"img/icons/{name}")


def test_login_page_and_app_pages_offer_the_install(client, caller):
    url = reverse("core:manifest")
    login_page = client.get(reverse("accounts:login")).content.decode()
    assert f'rel="manifest" href="{url}"' in login_page and "apple-touch-icon" in login_page
    client.force_login(caller)
    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert f'rel="manifest" href="{url}"' in page


def test_manifest_reveals_nothing_personal(client, caller):
    client.force_login(caller)
    assert caller.username not in client.get(reverse("core:manifest")).content.decode()
