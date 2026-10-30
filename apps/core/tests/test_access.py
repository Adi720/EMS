"""Server-side access control: deny-by-default login and the role matrix."""

import pytest
from django.urls import NoReverseMatch, URLResolver, get_resolver, reverse

# Views that are intentionally reachable without logging in.
PUBLIC_URL_NAMES = {"accounts:login", "core:healthz"}

# Expected status per role for each role-restricted page.
ROLE_MATRIX = {
    "core:caller_dashboard": {
        "caller": 200,
        "coordinator": 403,
        "caller_coordinator": 200,
        "sysadmin": 403,
        "no_role_user": 403,
    },
    "core:coordinator_dashboard": {
        "caller": 403,
        "coordinator": 200,
        "caller_coordinator": 200,
        "sysadmin": 200,
        "no_role_user": 403,
    },
}


def iter_url_names(resolver=None, prefix=""):
    resolver = resolver or get_resolver()
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            if pattern.namespace == "admin":  # Django Admin has its own staff login
                continue
            namespace = f"{prefix}{pattern.namespace}:" if pattern.namespace else prefix
            yield from iter_url_names(pattern, namespace)
        elif pattern.name:
            yield prefix + pattern.name


def protected_urls():
    for name in iter_url_names():
        if name in PUBLIC_URL_NAMES:
            continue
        try:
            yield name, reverse(name)
        except NoReverseMatch:  # needs arguments; covered by that view's own tests
            continue


@pytest.mark.django_db
@pytest.mark.parametrize(("name", "url"), list(protected_urls()))
def test_every_page_requires_login(client, name, url):
    response = client.get(url)
    assert response.status_code == 302, name
    assert response.url.startswith(reverse("accounts:login")), name


def test_role_matrix_covers_role_pages():
    names = {name for name, _ in protected_urls()}
    assert set(ROLE_MATRIX) <= names


@pytest.mark.parametrize(
    ("name", "fixture", "expected"),
    [(name, fixture, status) for name, roles in ROLE_MATRIX.items() for fixture, status in roles.items()],
)
def test_role_matrix(client, request, name, fixture, expected):
    client.force_login(request.getfixturevalue(fixture))
    assert client.get(reverse(name)).status_code == expected


@pytest.mark.parametrize(
    ("fixture", "target"),
    [
        ("caller", "core:caller_dashboard"),
        ("coordinator", "core:coordinator_dashboard"),
        ("caller_coordinator", "core:coordinator_dashboard"),
        ("sysadmin", "core:coordinator_dashboard"),
    ],
)
def test_home_redirects_to_role_dashboard(client, request, fixture, target):
    client.force_login(request.getfixturevalue(fixture))
    response = client.get(reverse("core:home"))
    assert response.status_code == 302
    assert response.url == reverse(target)


def test_home_without_role_is_denied(client, no_role_user):
    client.force_login(no_role_user)
    response = client.get(reverse("core:home"))
    assert response.status_code == 403
    assert b"No role assigned" in response.content


def test_caller_navigation_hides_coordinator_link(client, caller):
    client.force_login(caller)
    response = client.get(reverse("core:caller_dashboard"))
    assert reverse("core:coordinator_dashboard").encode() not in response.content


@pytest.mark.parametrize("fixture", ["caller", "coordinator"])
def test_django_admin_is_for_staff_only(client, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert reverse("admin:login") in response.url


def test_django_admin_allows_sysadmin(client, sysadmin):
    client.force_login(sysadmin)
    assert client.get(reverse("admin:index")).status_code == 200


@pytest.mark.django_db
def test_healthz_is_public_and_minimal(client):
    response = client.get(reverse("core:healthz"))
    assert response.status_code == 200
    assert response.content == b"ok"
