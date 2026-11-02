"""Calling ends by itself once the congregation's day has passed."""

from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.calling import services
from apps.calling.models import Outcome, SessionStatus

pytestmark = pytest.mark.django_db
SUNDAY = date(2026, 11, 8)


@pytest.fixture
def task(make_contact, allocate, make_session, caller):
    allocate(make_contact(full_name="Sunday Saint"), caller)
    return make_session(session_date=SUNDAY).tasks.get()


def test_calls_work_through_sunday_and_stop_on_monday(client, caller, task, record, clock):
    clock(SUNDAY)
    record(task, Outcome.WILL_TRY)  # the day itself still counts
    client.force_login(caller)
    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert "tel:" in page and "Update the result" in page

    clock(SUNDAY + timedelta(days=1))
    client.force_login(caller)  # the idle session from yesterday has expired
    with pytest.raises(services.CallingError, match="has finished"):
        record(task, Outcome.YES)  # even before anything has closed it
    response = client.post(
        reverse("calling:quick_attempt", args=[task.pk]), {"outcome": Outcome.YES}, follow=True
    )
    assert "has finished" in response.content.decode()
    task.refresh_from_db()
    assert task.attempt_count == 1 and task.latest_outcome == Outcome.WILL_TRY

    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert "tel:" not in page and "Update the result" not in page and "Calling is closed" in page
    task.session.refresh_from_db()
    assert task.session.status == SessionStatus.CLOSED
    detail = client.get(reverse("calling:task_detail", args=[task.pk])).content.decode()
    assert "tel:" not in detail and "Save result" not in detail


def test_daily_job_closes_finished_congregations(task, clock):
    call_command("weekly_reminders", date=SUNDAY.isoformat(), verbosity=0)
    task.session.refresh_from_db()
    assert task.session.status == SessionStatus.OPEN
    clock(SUNDAY + timedelta(days=1))
    call_command("weekly_reminders", date=(SUNDAY + timedelta(days=1)).isoformat())
    task.session.refresh_from_db()
    assert task.session.status == SessionStatus.CLOSED
    assert task.session.closed_at is not None


def test_future_and_draft_congregations_stay_as_they_are(make_session, clock):
    future = make_session(session_date=SUNDAY + timedelta(days=7))
    draft = make_session(session_date=date(2026, 10, 25), opened=False)
    clock(SUNDAY + timedelta(days=1))
    assert services.close_finished_sessions() == []
    future.refresh_from_db()
    draft.refresh_from_db()
    assert future.status == SessionStatus.OPEN and draft.status == SessionStatus.DRAFT


def test_reopening_allows_late_results_until_the_end_of_that_day(
    client, coordinator, caller, task, record, clock
):
    monday = SUNDAY + timedelta(days=1)
    clock(monday)
    services.close_finished_sessions()
    client.force_login(coordinator)
    response = client.post(reverse("calling:session_action", args=[task.session.pk, "open"]), follow=True)
    assert "closes again at the end of today" in response.content.decode()
    client.get(reverse("core:coordinator_dashboard"))  # must not undo the reopening
    task.session.refresh_from_db()
    assert task.session.status == SessionStatus.OPEN and task.session.late_until == monday
    record(task, Outcome.YES)

    clock(monday + timedelta(days=1))
    assert services.close_finished_sessions()[0].pk == task.session.pk
    with pytest.raises(services.CallingError):
        record(task, Outcome.NOT_POSSIBLE)


def test_results_and_reports_survive_closing(client, coordinator, task, record, clock):
    record(task, Outcome.YES)
    clock(SUNDAY + timedelta(days=1))
    client.force_login(coordinator)
    assert client.get(reverse("core:coordinator_dashboard")).status_code == 200
    task.refresh_from_db()
    assert task.latest_outcome == Outcome.YES
    assert task.attempts.count() == 1
