"""One person can hold several roles: each role's pages stay available, and no more."""

import pytest
from django.urls import reverse

from apps.accounts import team
from apps.accounts.roles import Role
from apps.calling import services
from apps.calling.models import Outcome
from apps.contacts.models import Contact

pytestmark = pytest.mark.django_db


@pytest.fixture
def coordinator_caller(make_user):
    return make_user("both", [Role.COORDINATOR, Role.CALLER], first_name="Both", last_name="Roles")


@pytest.fixture
def stall_caller(make_user):
    return make_user("stallcaller", [Role.STALL_LEAD, Role.CALLER], first_name="Stall", last_name="Caller")


def test_coordinator_who_calls_gets_both_sets_of_pages(
    client, coordinator_caller, coordinator, make_contact, allocate
):
    allocate(make_contact(full_name="Their Saint"), coordinator_caller)
    session, _, _ = services.start_weekly_calling(coordinator)
    task = session.tasks.get()
    client.force_login(coordinator_caller)
    assert client.get(reverse("core:home")).url == reverse("core:coordinator_dashboard")
    page = client.get(reverse("core:coordinator_dashboard")).content.decode()
    for label in ("My calls", "My Report", "Raise Request", "Calling Team", "Coordinator · Caller"):
        assert label in page
    assert "Their Saint" in client.get(reverse("core:caller_dashboard")).content.decode()
    client.post(reverse("calling:quick_attempt", args=[task.pk]), {"outcome": Outcome.YES})
    task.refresh_from_db()
    assert task.latest_outcome == Outcome.YES and task.attempts.get().recorded_by == coordinator_caller
    assert coordinator_caller in team.team_members()


def test_stall_lead_who_calls_gets_both_and_nothing_more(client, stall_caller, make_contact, allocate):
    allocate(make_contact(full_name="Stall Callers Saint"), stall_caller)
    client.force_login(stall_caller)
    assert client.get(reverse("core:home")).url == reverse("core:caller_dashboard")
    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert reverse("contacts:stall_add") in page and "Caller · Stall Lead" in page
    assert reverse("core:my_report") in page and reverse("caller_requests:mine") in page
    assert client.get(reverse("contacts:stall_add")).status_code == 200
    client.post(
        reverse("contacts:stall_add"),
        {
            "full_name": "From The Stall",
            "phone_primary": "98765 43218",
            "area": "Riverside",
            "registration_date": "2026-10-25",
            "collected_by_name": "Stall Caller",
        },
    )
    assert not Contact.objects.get(full_name="From The Stall").allocations.exists()
    for name in ("contacts:list", "allocations:home", "team:list", "core:coordinator_dashboard"):
        assert client.get(reverse(name)).status_code == 403, name


def test_plain_stall_lead_and_plain_caller_menus_are_unchanged(client, make_user, caller):
    client.force_login(make_user("stallonly", [Role.STALL_LEAD]))
    page = client.get(reverse("contacts:stall_add")).content.decode()
    assert reverse("core:caller_dashboard") not in page
    client.force_login(caller)
    assert reverse("contacts:stall_add") not in client.get(reverse("core:caller_dashboard")).content.decode()
