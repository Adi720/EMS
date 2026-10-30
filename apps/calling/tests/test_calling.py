from datetime import date

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.calling import services
from apps.calling.models import CallAttempt, CallTask, Outcome, ReportCategory, TaskStatus
from apps.contacts.models import ContactStatus, StatusReason
from apps.contacts.services import change_status
from conftest import SESSION_DATE


@pytest.fixture
def setup(make_contact, caller, caller2, allocate):
    """Two contacts for caller, one for caller2, one unallocated, one inactive."""
    mine = [make_contact(full_name=f"Mine {i}") for i in range(2)]
    theirs = make_contact(full_name="Theirs")
    unallocated = make_contact(full_name="Nobody's")
    for contact in mine:
        allocate(contact, caller)
    allocate(theirs, caller2)
    return {"mine": mine, "theirs": theirs, "unallocated": unallocated}


def test_opening_session_creates_one_task_per_eligible_contact(
    setup, make_session, caller, caller2, coordinator
):
    session = make_session()
    tasks = {t.contact.full_name: t for t in session.tasks.select_related("contact", "caller")}
    assert set(tasks) == {"Mine 0", "Mine 1", "Theirs"}
    assert tasks["Mine 0"].caller == caller and tasks["Theirs"].caller == caller2
    assert tasks["Mine 0"].allocation is not None
    assert services.refresh_session(session, coordinator) == {}  # idempotent
    assert session.tasks.count() == 3


def test_duplicate_task_is_rejected_by_database(setup, make_session):
    session = make_session()
    task = session.tasks.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        CallTask.objects.create(session=session, contact=task.contact, caller=task.caller)


def test_task_uses_allocation_in_effect_on_session_date(
    make_contact, caller, caller2, allocate, make_session
):
    contact = make_contact()
    allocate(contact, caller)
    allocate(contact, caller2, effective_date=date(2026, 11, 2))  # starts after the session
    session = make_session(session_date=SESSION_DATE)
    assert session.tasks.get().caller == caller


@pytest.mark.parametrize("outcome", Outcome.values)
def test_each_outcome_completes_the_task(setup, make_session, record, outcome):
    task = make_session().tasks.filter(contact=setup["mine"][0]).get()
    record(task, outcome)
    task.refresh_from_db()
    assert task.is_completed and task.attempt_count == 1 and task.latest_outcome == outcome
    expected = ReportCategory.UNKNOWN if outcome == Outcome.NOT_CONNECTED else ReportCategory(outcome)
    assert task.report_category == expected
    assert task.is_connected is (outcome != Outcome.NOT_CONNECTED)


def test_repeated_attempts_keep_history_and_latest_wins(setup, make_session, record):
    task = make_session().tasks.filter(contact=setup["mine"][0]).get()
    record(task, Outcome.NOT_CONNECTED, notes="No answer")
    record(task, Outcome.WILL_TRY)
    record(task, Outcome.YES, notes="Coming with a friend")
    task.refresh_from_db()
    assert task.attempt_count == 3 and task.latest_outcome == Outcome.YES
    assert list(task.attempts.order_by("id").values_list("outcome", flat=True)) == [
        Outcome.NOT_CONNECTED,
        Outcome.WILL_TRY,
        Outcome.YES,
    ]
    attempt = task.attempts.first()
    with pytest.raises(ValueError):
        attempt.save()  # append-only


def test_cross_caller_recording_is_denied_but_coordinator_may(
    setup, make_session, record, caller, coordinator
):
    session = make_session()
    theirs = session.tasks.get(contact=setup["theirs"])
    with pytest.raises(PermissionDenied):
        record(theirs, Outcome.YES, actor=caller)
    attempt = record(theirs, Outcome.YES, actor=coordinator)
    assert attempt.recorded_by == coordinator
    assert CallAttempt.objects.count() == 1


def test_closed_session_withdrawn_task_and_do_not_call_block_attempts(
    setup, make_session, record, coordinator
):
    session = make_session()
    task_a, task_b = session.tasks.filter(contact__in=setup["mine"]).order_by("contact__full_name")
    change_status(
        task_a.contact, ContactStatus.INACTIVE, coordinator, reason_category=StatusReason.MOVED_AWAY
    )
    with pytest.raises(services.CallingError):
        record(task_a, Outcome.YES)  # withdrawn
    services.close_session(session, coordinator)
    with pytest.raises(services.CallingError):
        record(task_b, Outcome.YES)


def test_mid_session_reassignment_moves_only_unattempted(
    setup, make_session, record, allocate, caller, caller2
):
    session = make_session()
    attempted, untouched = (session.tasks.get(contact=c) for c in setup["mine"])
    record(attempted, Outcome.NOT_CONNECTED)
    for contact in setup["mine"]:
        allocate(contact, caller2, effective_date=date(2026, 10, 31))
    attempted.refresh_from_db()
    untouched.refresh_from_db()
    assert attempted.caller == caller  # stays credited to the original caller
    assert untouched.caller == caller2
    assert attempted.attempts.count() == 1


def test_inactive_withdraws_unattempted_keeps_attempted(setup, make_session, record, coordinator):
    session = make_session()
    attempted, untouched = (session.tasks.get(contact=c) for c in setup["mine"])
    record(attempted, Outcome.YES)
    for contact in setup["mine"]:
        change_status(
            contact, ContactStatus.DO_NOT_CALL, coordinator, reason_category=StatusReason.REQUESTED_NO_CALLS
        )
    attempted.refresh_from_db()
    untouched.refresh_from_db()
    assert attempted.status == TaskStatus.OPEN and attempted.latest_outcome == Outcome.YES
    assert untouched.status == TaskStatus.WITHDRAWN
    assert "Do not call" in untouched.withdrawn_reason


def test_caller_cannot_open_own_withdrawn_task(client, setup, make_session, caller, coordinator):
    session = make_session()
    task = session.tasks.get(contact=setup["mine"][0])
    change_status(task.contact, ContactStatus.INACTIVE, coordinator, reason_category=StatusReason.MOVED_AWAY)
    client.force_login(caller)
    assert client.get(reverse("calling:task_detail", args=[task.pk])).status_code == 404


def test_inactive_or_do_not_call_contacts_cannot_be_allocated(make_contact, caller, coordinator):
    from apps.allocations.services import AllocationError, assign_individual

    for status in (ContactStatus.INACTIVE, ContactStatus.DO_NOT_CALL):
        contact = make_contact()
        change_status(contact, status, coordinator, reason_category=StatusReason.OTHER)
        with pytest.raises(AllocationError):
            assign_individual(contact, caller, effective_date=date(2026, 6, 1), actor=coordinator, reason="x")
        assert not contact.allocations.exists()


def test_database_never_withdraws_attempted_task(setup, make_session, record):
    task = make_session().tasks.filter(contact=setup["mine"][0]).get()
    record(task, Outcome.YES)
    with pytest.raises(IntegrityError), transaction.atomic():
        CallTask.objects.filter(pk=task.pk).update(status=TaskStatus.WITHDRAWN)


# --- Views -------------------------------------------------------------------------


def test_caller_dashboard_lists_only_own_tasks(client, setup, make_session, caller):
    make_session()
    client.force_login(caller)
    response = client.get(reverse("core:caller_dashboard"))
    names = {t.contact.full_name for t in response.context["tasks"]}
    assert names == {"Mine 0", "Mine 1"}
    assert b"Theirs" not in response.content
    assert response.context["summary"]["assigned"] == 2


def test_caller_cannot_open_other_callers_task(client, setup, make_session, caller):
    session = make_session()
    theirs = session.tasks.get(contact=setup["theirs"])
    client.force_login(caller)
    assert client.get(reverse("calling:task_detail", args=[theirs.pk])).status_code == 404
    response = client.post(reverse("calling:quick_attempt", args=[theirs.pk]), {"outcome": "yes"})
    assert response.status_code == 404
    response = client.post(reverse("calling:task_detail", args=[theirs.pk]), {"outcome": "yes"})
    assert response.status_code == 404
    assert not CallAttempt.objects.exists()


def test_caller_cannot_request_other_callers_session_view(
    client, setup, make_session, caller, make_contact, allocate, caller2
):
    other_session = make_session(session_date=date(2026, 11, 8))
    other_session.tasks.filter(caller=caller).delete()  # caller has no tasks there
    client.force_login(caller)
    assert client.get(reverse("core:caller_dashboard"), {"session": other_session.pk}).status_code == 404


def test_quick_attempt_and_detail_form(client, setup, make_session, caller):
    session = make_session()
    task = session.tasks.get(contact=setup["mine"][0])
    client.force_login(caller)
    response = client.post(reverse("calling:quick_attempt", args=[task.pk]), {"outcome": "will_try"})
    assert response.status_code == 302
    response = client.post(
        reverse("calling:task_detail", args=[task.pk]),
        {"outcome": "yes", "notes": "Confirmed", "callback_at": ""},
    )
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.attempt_count == 2 and task.latest_outcome == Outcome.YES
    response = client.post(reverse("calling:quick_attempt", args=[task.pk]), {"outcome": "maybe"})
    task.refresh_from_db()
    assert task.attempt_count == 2  # invalid outcome rejected


def test_do_not_call_phone_hidden_from_caller(client, setup, make_session, record, caller, coordinator):
    session = make_session()
    task = session.tasks.get(contact=setup["mine"][0])
    record(task, Outcome.NOT_CONNECTED)
    change_status(
        task.contact, ContactStatus.DO_NOT_CALL, coordinator, reason_category=StatusReason.REQUESTED_NO_CALLS
    )
    client.force_login(caller)
    phone = task.contact.phone_primary
    for url in [reverse("core:caller_dashboard"), reverse("calling:task_detail", args=[task.pk])]:
        content = client.get(url).content.decode()
        assert phone not in content and task.contact.phone_display not in content
        assert "Do not call" in content


def test_session_management_is_coordinator_only(client, setup, make_session, caller):
    session = make_session()
    client.force_login(caller)
    assert client.get(reverse("calling:session_list")).status_code == 403
    assert client.get(reverse("calling:session_detail", args=[session.pk])).status_code == 403
    assert client.post(reverse("calling:session_action", args=[session.pk, "close"])).status_code == 403
    session.refresh_from_db()
    assert session.is_open


def test_coordinator_session_lifecycle_via_views(client, setup, coordinator):
    client.force_login(coordinator)
    response = client.post(
        reverse("calling:session_create"),
        {"session_date": "2026-11-01", "title": "", "venue": "", "notes": ""},
    )
    assert response.status_code == 302
    from apps.calling.models import EmsSession

    session = EmsSession.objects.get()
    assert session.status == "draft" and not session.tasks.exists()
    client.post(reverse("calling:session_action", args=[session.pk, "open"]))
    assert session.tasks.count() == 3
    response = client.post(
        reverse("calling:session_create"),
        {"session_date": "2026-11-01", "title": "", "venue": "", "notes": ""},
    )
    assert response.status_code == 200  # duplicate date + venue rejected
    client.post(reverse("calling:session_action", args=[session.pk, "close"]))
    session.refresh_from_db()
    assert session.status == "closed"


# --- One-click weekly start --------------------------------------------------------


def test_congregation_label_format(make_session):
    assert str(make_session(session_date=date(2026, 11, 1), opened=False)) == "EMS Congregation (1/11/26)"


def test_next_sunday():
    assert services.next_sunday(date(2026, 10, 31)) == date(2026, 11, 1)  # Saturday → next day
    assert services.next_sunday(date(2026, 11, 1)) == date(2026, 11, 1)  # Sunday → today
    assert services.next_sunday(date(2026, 11, 2)) == date(2026, 11, 8)  # Monday → next Sunday


def test_start_weekly_calling_creates_opens_and_closes_previous(setup, make_session, coordinator):
    last_week = make_session(session_date=date(2026, 10, 25))
    session, totals, closed = services.start_weekly_calling(coordinator, today=date(2026, 10, 31))
    assert session.session_date == date(2026, 11, 1) and session.is_open
    assert totals == {"created": 3} and session.tasks.count() == 3
    last_week.refresh_from_db()
    assert closed == [last_week] and last_week.status == "closed"
    again, totals, closed = services.start_weekly_calling(coordinator, today=date(2026, 10, 31))
    assert again == session and totals == {} and closed == []  # second click changes nothing
    assert session.tasks.count() == 3


def test_start_weekly_calling_refuses_closed_congregation(setup, make_session, coordinator):
    session = make_session(session_date=date(2026, 11, 1))
    services.close_session(session, coordinator)
    with pytest.raises(services.CallingError):
        services.start_weekly_calling(coordinator, today=date(2026, 10, 31))


def test_start_week_button_is_coordinator_only(client, setup, caller, coordinator):
    from apps.calling.models import EmsSession

    client.force_login(caller)
    assert client.post(reverse("calling:start_week")).status_code == 403
    assert not EmsSession.objects.exists()
    client.force_login(coordinator)
    assert client.get(reverse("calling:start_week")).status_code == 405  # POST only
    response = client.post(reverse("calling:start_week"))
    assert response.status_code == 302
    session = EmsSession.objects.get()
    assert session.is_open and session.session_date.weekday() == 6
    dashboard = client.get(reverse("core:coordinator_dashboard")).content.decode()
    assert f"Calling is open for <strong>{session}</strong>" in dashboard
