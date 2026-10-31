"""Calling Team statuses: Active, Partially Active (< 75% attempted), On Leave, Inactive."""

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts import performance, team
from apps.accounts.performance import TeamStatus
from apps.allocations.services import current_allocation
from apps.caller_requests.models import RequestKind
from apps.caller_requests.services import decide, raise_request
from apps.calling.models import Outcome

pytestmark = pytest.mark.django_db
SUNDAY = date(2026, 10, 25)
LATER = date(2026, 11, 2)  # the Monday after; SUNDAY is inside the last month


@pytest.fixture
def four_calls(make_contact, allocate, make_session, caller, record):
    saints = [make_contact(full_name=f"Saint {i}") for i in range(4)]
    for saint in saints:
        allocate(saint, caller)
    session = make_session(session_date=SUNDAY)
    tasks = list(session.tasks.order_by("contact__full_name"))
    return tasks, record


def test_partially_active_below_75_percent(caller, four_calls):
    tasks, record = four_calls
    for task in tasks[:2]:
        record(task, Outcome.YES)
    row = performance.performance(today=LATER, callers=[caller])[caller.pk]
    assert (row["assigned"], row["completed"], row["completion_rate"]) == (4, 2, 50)
    assert performance.team_status(caller, row) == TeamStatus.PARTIALLY_ACTIVE

    record(tasks[2], Outcome.NOT_CONNECTED)  # any attempt counts
    row = performance.performance(today=LATER, callers=[caller])[caller.pk]
    assert row["completion_rate"] == 75
    assert performance.team_status(caller, row) == TeamStatus.ACTIVE


def test_no_calls_yet_is_active_and_old_weeks_drop_out(caller, four_calls):
    assert performance.status_for(caller, today=SUNDAY) == TeamStatus.ACTIVE  # congregation not over
    assert performance.status_for(caller, today=date(2027, 1, 5)) == TeamStatus.ACTIVE  # outside window
    assert performance.status_for(caller, today=LATER) == TeamStatus.PARTIALLY_ACTIVE


def test_caller_sees_a_gentle_note_when_partially_active(
    client, caller, make_contact, allocate, make_session
):
    allocate(make_contact(), caller)
    make_session(session_date=timezone.localdate() - timedelta(days=3))  # not called at all
    client.force_login(caller)
    content = client.get(reverse("core:caller_dashboard")).content.decode()
    assert "The goal is 75%" in content


def test_leave_moves_saints_and_return_can_move_some_back(
    client, coordinator, caller, caller2, make_contact, allocate
):
    saints = [make_contact(full_name=f"Leave Saint {i}") for i in range(3)]
    for saint in saints:
        allocate(saint, caller)
    client.force_login(coordinator)
    response = client.post(reverse("team:leave", args=[caller.pk]), {"reason": "Travelling"})
    assert response.status_code == 302 and "move_all" in response.url
    caller.refresh_from_db()
    assert caller.is_on_leave and performance.status_for(caller) == TeamStatus.ON_LEAVE
    assert (
        "is On Leave and still has 3 Saints"
        in client.get(reverse("core:coordinator_dashboard")).content.decode()
    )

    for saint in saints:  # the coordinator gives the Saints to someone else
        allocate(saint, caller2, effective_date=caller.on_leave_since)
    moved = team.saints_moved_during_leave(caller)
    assert len(moved) == 3
    page = client.get(reverse("team:return", args=[caller.pk])).content.decode()
    assert "Leave Saint 0" in page and "now with" in page

    client.post(reverse("team:return", args=[caller.pk]), {"move_back": [moved[0].pk]})
    caller.refresh_from_db()
    assert not caller.is_on_leave
    assert current_allocation(moved[0].contact).caller == caller  # ticked: back
    assert current_allocation(moved[1].contact).caller == caller2  # default: stays


def test_caller_can_ask_for_a_break(caller, coordinator):
    request = raise_request(caller, RequestKind.ON_LEAVE, "Exams for two months")
    decide(request, coordinator, approve=True)
    caller.refresh_from_db()
    assert caller.is_on_leave


def test_performance_page_is_sorted_and_coordinator_only(
    client, coordinator, caller, caller2, make_contact, allocate, make_session, record
):
    for i, who in enumerate([caller, caller, caller2, caller2]):
        allocate(make_contact(full_name=f"P{i}"), who)
    session = make_session(session_date=timezone.localdate() - timedelta(days=3))
    for task in session.tasks.filter(caller=caller2):
        record(task, Outcome.YES)
    client.force_login(coordinator)
    page = client.get(reverse("team:performance"), {"months": 3}).content.decode()
    assert page.index(str(caller2)) < page.index(str(caller))  # 100% before 0%
    assert "Partially Active" in page
    client.force_login(caller)
    assert client.get(reverse("team:performance")).status_code == 403
