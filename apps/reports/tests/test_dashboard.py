"""Coordinator dashboard states, setup checklist and the new application shell."""

from datetime import date

import pytest
from django.urls import reverse

from apps.calling.services import close_session, next_sunday
from apps.core.templatetags.ui import initials, percent
from apps.imports.models import ImportBatch

DASHBOARD = reverse("core:coordinator_dashboard")


def overview(client):
    return client.get(DASHBOARD).context["overview"]


@pytest.fixture
def coord_client(client, coordinator):
    client.force_login(coordinator)
    return client


def test_empty_system_shows_setup_checklist(coord_client):
    response = coord_client.get(DASHBOARD)
    ov = response.context["overview"]
    assert ov["state"] == "setup"
    assert [s["key"] for s in ov["steps_remaining"]] == ["callers", "saints", "assignments", "calling"]
    assert ov["next_step"]["key"] == "callers"
    content = response.content.decode()
    assert "Let&#x27;s get Calling Seva ready" in content or "Let's get Calling Seva ready" in content
    assert "0 of 4" in content


def test_completed_steps_are_hidden_and_staged_import_is_linked(coord_client, caller, coordinator):
    batch = ImportBatch.objects.create(
        uploaded_by=coordinator,
        original_filename="synthetic.xlsx",
        file_sha256="0" * 64,
        file_type="xlsx",
        contact_sheet="EMS STALL SEWA",
    )
    ov = overview(coord_client)
    keys = [s["key"] for s in ov["steps_remaining"]]
    assert "callers" not in keys and ov["steps_done"] == 1
    saints = ov["next_step"]
    assert saints["key"] == "saints"
    assert saints["url"] == reverse("imports:detail", args=[batch.pk])
    assert f"Continue import #{batch.pk}" in saints["action"]


def test_real_counts_and_unallocated_warning(coord_client, caller, make_contact, allocate):
    allocated = [make_contact() for _ in range(3)]
    for contact in allocated:
        allocate(contact, caller)
    make_contact()  # active but no caller
    response = coord_client.get(DASHBOARD)
    ov = response.context["overview"]
    assert (ov["active_saints"], ov["caller_count"], ov["allocated"], ov["unallocated"]) == (4, 1, 3, 1)
    assert ov["state"] == "ready"
    assert "1 without a caller" in response.content.decode()


def test_ready_calling_and_completed_states(coord_client, caller, coordinator, make_contact, allocate):
    allocate(make_contact(), caller)
    response = coord_client.get(DASHBOARD)
    assert response.context["overview"]["state"] == "ready"
    assert reverse("calling:start_week") in response.content.decode()

    coord_client.post(reverse("calling:start_week"))
    response = coord_client.get(DASHBOARD)
    session = response.context["week_session"]
    assert response.context["overview"]["state"] == "calling"
    assert f"Calling is open for <strong>{session}</strong>" in response.content.decode()
    assert response.context["summary"]["assigned"] == 1

    close_session(session, coordinator)
    response = coord_client.get(DASHBOARD)
    assert response.context["overview"]["state"] == "completed"
    assert "View results" in response.content.decode()


def test_add_caller_uses_in_app_team_management(client, coordinator):
    client.force_login(coordinator)
    content = client.get(DASHBOARD).content.decode()
    assert reverse("team:create") in content
    assert reverse("admin:accounts_user_add") not in content


def test_navigation_by_role(client, caller, coordinator):
    client.force_login(coordinator)
    content = client.get(DASHBOARD).content.decode()
    assert ">Saints<" in content and ">Team<" in content and ">Assignments<" in content
    assert 'class="ems-nav__link active" href="/coordinator/" aria-current="page"' in content

    client.force_login(caller)
    content = client.get(reverse("core:caller_dashboard")).content.decode()
    for coordinator_only in [
        "contacts:list",
        "team:list",
        "allocations:home",
        "imports:list",
        "audit:event_list",
        "reports:monthly",
    ]:
        assert f'href="{reverse(coordinator_only)}"' not in content, coordinator_only
    assert 'class="ems-nav__link active" href="/my-calls/" aria-current="page"' in content


@pytest.mark.django_db
def test_anonymous_error_page_renders_in_public_layout(client):
    response = client.get("/accounts/does-not-exist/")
    assert response.status_code == 404
    assert b"Page not found" in response.content and b"ems-bare-header" in response.content


def test_ui_helpers(make_user):
    assert initials(make_user("x1", first_name="Shalini", last_name="Ji")) == "SJ"
    assert initials(make_user("vansh_ji")) == "V"
    assert percent(1, 3) == 33 and percent(5, 0) == 0


def test_week_label_is_coming_sunday(coord_client):
    sunday = next_sunday()
    assert coord_client.get(DASHBOARD).context["week_label"] == (
        f"EMS Congregation ({sunday.day}/{sunday.month}/{sunday:%y})"
    )
    assert sunday.weekday() == 6 and sunday >= date.today()
