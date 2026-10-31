"""Session lifecycle, call-task synchronisation and attempt recording.

``sync_contact_tasks`` is the single rule for what a contact's task in an open
session should be (decision log 17/18):

* eligible = contact is Active and has an allocation in effect on the session date;
* an attempted task is never moved or withdrawn (work stays credited);
* an unattempted task follows the allocation's caller, or is withdrawn when the
  contact is no longer eligible; it is reinstated if the contact becomes eligible again.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.allocations.models import Allocation
from apps.allocations.services import active_on_filter, allocation_on
from apps.audit.services import log_event
from apps.contacts.models import CALLABLE_STATUSES, Contact

from .models import CallAttempt, CallTask, EmsSession, Outcome, SessionStatus, TaskStatus


class CallingError(Exception):
    pass


def _withdraw_reason(contact, allocation):
    if contact.status not in CALLABLE_STATUSES:
        return f"Contact is {contact.get_status_display()}"
    if allocation is None:
        return "No caller allocated on the session date"
    return ""


def _sync_one(session, contact, actor):
    allocation = allocation_on(contact, session.session_date)
    eligible = contact.status in CALLABLE_STATUSES and allocation is not None
    task = CallTask.objects.select_for_update().filter(session=session, contact=contact).first()

    if task is None:
        if not eligible:
            return None
        task = CallTask.objects.create(
            session=session, contact=contact, caller=allocation.caller, allocation=allocation
        )
        return "created"
    if task.attempt_count > 0:
        return None
    if eligible:
        if task.status == TaskStatus.OPEN and task.caller_id == allocation.caller_id:
            if task.allocation_id != allocation.pk:
                task.allocation = allocation
                task.save(update_fields=["allocation", "updated_at"])
            return None
        result = "moved" if task.status == TaskStatus.OPEN else "reinstated"
        previous = task.caller
        task.status = TaskStatus.OPEN
        task.caller = allocation.caller
        task.allocation = allocation
        task.withdrawn_reason = ""
        task.withdrawn_at = None
        task.save()
        log_event(
            actor,
            f"task.{result}",
            f"{contact} ({session}): task {result} {previous} → {task.caller}",
            task,
            from_caller=previous.pk,
            to_caller=task.caller_id,
        )
        return result
    if task.status == TaskStatus.OPEN:
        task.status = TaskStatus.WITHDRAWN
        task.withdrawn_reason = _withdraw_reason(contact, allocation)
        task.withdrawn_at = timezone.now()
        task.save()
        log_event(actor, "task.withdrawn", f"{contact} ({session}): {task.withdrawn_reason}", task)
        return "withdrawn"
    return None


def _tally(results):
    totals = {}
    for result in results:
        if result:
            totals[result] = totals.get(result, 0) + 1
    return totals


@transaction.atomic
def sync_contact_tasks(contact, actor=None):
    contact = Contact.objects.get(pk=contact.pk)
    sessions = EmsSession.objects.filter(status=SessionStatus.OPEN)
    return _tally(_sync_one(session, contact, actor) for session in sessions)


@transaction.atomic
def generate_session_tasks(session, actor=None):
    """Create/refresh tasks for every contact allocated on the session date (idempotent)."""
    if session.status != SessionStatus.OPEN:
        raise CallingError("Call lists can only be built while calling is open.")
    allocated = Allocation.objects.filter(active_on_filter(session.session_date)).values("contact_id")
    contacts = (
        Contact.objects.filter(Q(pk__in=allocated) | Q(call_tasks__session=session)).distinct().order_by("pk")
    )
    return _tally(_sync_one(session, contact, actor) for contact in contacts)


@transaction.atomic
def create_session(*, session_date, title, venue, notes, actor):
    session = EmsSession(session_date=session_date, title=title, venue=venue, notes=notes, created_by=actor)
    session.full_clean()
    session.save()
    log_event(actor, "session.create", f"Created {session}", session)
    return session


@transaction.atomic
def update_session(session, data, actor):
    changed = [k for k, v in data.items() if getattr(session, k) != v]
    if not changed:
        return session
    if "session_date" in changed and session.tasks.exists():
        raise CallingError("The date cannot change once call lists exist for this congregation.")
    for key in changed:
        setattr(session, key, data[key])
    session.full_clean()
    session.save()
    log_event(actor, "session.update", f"Edited {session}", session, fields=changed)
    return session


@transaction.atomic
def open_session(session, actor):
    session = EmsSession.objects.select_for_update().get(pk=session.pk)
    if session.status == SessionStatus.OPEN:
        raise CallingError("Calling is already open for this congregation.")
    previous = session.status
    session.status = SessionStatus.OPEN
    session.opened_at = timezone.now()
    session.closed_at = None
    session.save()
    totals = generate_session_tasks(session, actor)
    action = "session.reopen" if previous == SessionStatus.CLOSED else "session.open"
    log_event(actor, action, f"Opened {session} for calling", session, tasks=totals)
    return session, totals


@transaction.atomic
def close_session(session, actor):
    session = EmsSession.objects.select_for_update().get(pk=session.pk)
    if session.status != SessionStatus.OPEN:
        raise CallingError("Calling is not open for this congregation.")
    session.status = SessionStatus.CLOSED
    session.closed_at = timezone.now()
    session.save()
    log_event(actor, "session.close", f"Closed {session}", session)
    return session


@transaction.atomic
def refresh_session(session, actor):
    totals = generate_session_tasks(session, actor)
    log_event(actor, "session.refresh", f"Refreshed tasks for {session}", session, tasks=totals)
    return totals


def next_sunday(today=None):
    """The coming Sunday (today, if today is Sunday)."""
    today = today or timezone.localdate()
    return today + timedelta(days=(6 - today.weekday()) % 7)


@transaction.atomic
def start_weekly_calling(actor, today=None):
    """One click: create the coming Sunday's congregation if needed, open calling for it,
    and close calling for any earlier congregation still open.

    Returns (session, task totals, congregations closed).
    """
    from apps.contacts.services import promote_new_saints

    promote_new_saints(today)
    sunday = next_sunday(today)
    session = EmsSession.objects.select_for_update().filter(session_date=sunday, venue="").first()
    if session and session.status == SessionStatus.CLOSED:
        raise CallingError(f"Calling for {session} is already closed. Reopen it from its page if needed.")
    if session and session.on_hold:
        raise CallingError(f"There is no Calling Sewa for {session.label}. Switch the hold off first.")
    closed = [
        close_session(earlier, actor)
        for earlier in EmsSession.objects.filter(status=SessionStatus.OPEN, session_date__lt=sunday)
    ]
    if session is None:
        session = create_session(session_date=sunday, title="", venue="", notes="", actor=actor)
    if session.status == SessionStatus.OPEN:
        return session, {}, closed
    session, totals = open_session(session, actor)
    return session, totals, closed


def can_record(user, task):
    return user.is_coordinator or (user.is_caller and task.caller_id == user.pk)


@transaction.atomic
def record_attempt(task, *, outcome, actor, notes="", callback_at=None):
    task = CallTask.objects.select_for_update().select_related("session", "contact").get(pk=task.pk)
    if not can_record(actor, task):
        raise PermissionDenied
    if outcome not in Outcome.values:
        raise CallingError("Choose one of the four outcomes.")
    if task.session.status != SessionStatus.OPEN:
        raise CallingError("Calling is not open for this congregation.")
    if task.session.on_hold:
        raise CallingError("There is no Calling Sewa this week; results cannot be recorded.")
    if task.status != TaskStatus.OPEN:
        raise CallingError("This task has been withdrawn.")

    attempt = CallAttempt.objects.create(
        task=task, outcome=outcome, notes=notes, callback_at=callback_at, recorded_by=actor
    )
    task.attempt_count += 1
    task.latest_outcome = outcome
    task.last_attempt_at = attempt.attempted_at
    task.callback_at = callback_at
    task.save()
    log_event(
        actor,
        "call.attempt",
        f"{task.contact} ({task.session}): {attempt.get_outcome_display()}",
        task,
        attempt=attempt.pk,
        outcome=outcome,
        on_behalf_of=task.caller_id if task.caller_id != actor.pk else None,
    )
    return attempt


@transaction.atomic
def set_week_hold(actor, on_hold, *, note="", today=None):
    """Switch "No Calling Sewa this week" for the coming Sunday's congregation."""
    sunday = next_sunday(today)
    session = EmsSession.objects.select_for_update().filter(session_date=sunday, venue="").first()
    if session is None:
        if not on_hold:
            return None
        session = create_session(session_date=sunday, title="", venue="", notes="", actor=actor)
    session.on_hold = on_hold
    session.hold_note = note.strip()[:200] if on_hold else ""
    session.save(update_fields=["on_hold", "hold_note"])
    log_event(
        actor,
        "session.hold" if on_hold else "session.resume",
        f"{'No Calling Sewa' if on_hold else 'Calling Sewa back on'} for {session.label}",
        session,
        note=session.hold_note,
    )
    return session
