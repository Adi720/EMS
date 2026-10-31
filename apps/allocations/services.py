"""Allocation planning (preview) and atomic application.

Every change goes through ``plan_*`` → ``apply_plan``. A plan is a list of
``PlannedChange`` computed from the current open allocations; applying it locks
the contacts, re-checks that nothing changed since the preview, closes the
current allocation on the effective date and opens the new one.
"""

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.audit.services import log_event
from apps.contacts.models import CALLABLE_STATUSES, Contact, ContactStatus
from apps.core.dates import add_months

from .models import Allocation, AllocationCycle, AllocationOperation, ChangeType, CycleStatus


class AllocationError(Exception):
    pass


# These statuses end the allocation (requirements §6); they must be reactivated first.
CANNOT_ALLOCATE = frozenset({ContactStatus.INACTIVE})


@dataclass(frozen=True)
class PlannedChange:
    contact: Contact
    from_caller: User | None
    to_caller: User | None

    @property
    def key(self):
        return (self.contact.pk, getattr(self.from_caller, "pk", None), getattr(self.to_caller, "pk", None))


# --- Queries ---------------------------------------------------------------


def callers_queryset():
    return User.objects.filter(is_active=True, groups__name=Role.CALLER).distinct()


def current_allocation(contact):
    return (
        Allocation.objects.filter(contact=contact, effective_to__isnull=True).select_related("caller").first()
    )


def allocation_on(contact, day):
    return (
        Allocation.objects.filter(contact=contact, effective_from__lte=day)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=day))
        .select_related("caller")
        .first()
    )


def active_on_filter(day, prefix=""):
    """Q() selecting allocations in effect on ``day``."""
    return Q(**{f"{prefix}effective_from__lte": day}) & (
        Q(**{f"{prefix}effective_to__isnull": True}) | Q(**{f"{prefix}effective_to__gt": day})
    )


def open_allocations():
    return Allocation.objects.filter(effective_to__isnull=True)


def caller_list_counts():
    """Current (open) allocation counts per caller, including callers with none."""
    counts = dict(open_allocations().values("caller").annotate(n=Count("id")).values_list("caller", "n"))
    callers = list(callers_queryset())
    extra = User.objects.filter(pk__in=set(counts) - {c.pk for c in callers})
    return [(user, counts.get(user.pk, 0)) for user in [*callers, *extra]]


def unallocated_active_contacts():
    return Contact.objects.filter(status__in=CALLABLE_STATUSES).exclude(pk__in=allocated_contact_ids())


def allocated_contact_ids():
    """Contacts with an open allocation. An explicit subquery: a join-based
    ``allocations__effective_to__isnull=True`` also matches contacts with no allocation at all."""
    return open_allocations().values("contact_id")


# --- Planning --------------------------------------------------------------


def _current_map(contacts):
    allocations = open_allocations().filter(contact__in=contacts).select_related("caller")
    return {a.contact_id: a for a in allocations}


def plan_assign(contacts, to_caller):
    """Assign or move the selected contacts to ``to_caller``."""
    contacts = list(contacts)
    current = _current_map(contacts)
    changes = []
    for contact in contacts:
        alloc = current.get(contact.pk)
        from_caller = alloc.caller if alloc else None
        if from_caller != to_caller:
            changes.append(PlannedChange(contact, from_caller, to_caller))
    return changes


def _list_of(caller):
    return [
        a.contact
        for a in open_allocations()
        .filter(caller=caller)
        .select_related("contact", "caller")
        .order_by("contact__full_name")
    ]


def plan_move_all(from_caller, to_caller):
    if from_caller == to_caller:
        raise AllocationError("Choose two different callers.")
    return [PlannedChange(c, from_caller, to_caller) for c in _list_of(from_caller)]


def plan_swap(caller_a, caller_b):
    if caller_a == caller_b:
        raise AllocationError("Choose two different callers.")
    return [PlannedChange(c, caller_a, caller_b) for c in _list_of(caller_a)] + [
        PlannedChange(c, caller_b, caller_a) for c in _list_of(caller_b)
    ]


def plan_rotate(callers):
    """Each caller's whole list moves to the next caller; the last list goes to the first."""
    callers = list(callers)
    if len(callers) < 2 or len(set(callers)) != len(callers):
        raise AllocationError("Choose at least two different callers, in rotation order.")
    changes = []
    for index, caller in enumerate(callers):
        target = callers[(index + 1) % len(callers)]
        changes.extend(PlannedChange(c, caller, target) for c in _list_of(caller))
    return changes


def plan_fingerprint(changes):
    payload = ";".join(f"{c}:{f}:{t}" for c, f, t in sorted(ch.key for ch in changes))
    return hashlib.sha256(payload.encode()).hexdigest()


def check_plan(changes, effective_date):
    """Return (errors, warnings) for a plan."""
    errors, warnings = [], []
    if not changes:
        errors.append("No allocation would change.")
    current = _current_map([ch.contact for ch in changes])
    too_early = [
        ch.contact
        for ch in changes
        if (a := current.get(ch.contact.pk)) and a.effective_from > effective_date
    ]
    if too_early:
        names = ", ".join(str(c) for c in too_early[:5])
        errors.append(
            f"Effective date is before the current allocation started for {len(too_early)} contact(s) ({names})."
        )
    # Read statuses from the database: the Contact objects in a plan may be stale.
    status_of = dict(
        Contact.objects.filter(pk__in=[ch.contact.pk for ch in changes]).values_list("pk", "status")
    )
    closed = [
        ch.contact for ch in changes if ch.to_caller and status_of.get(ch.contact.pk) in CANNOT_ALLOCATE
    ]
    if closed:
        names = ", ".join(str(c) for c in closed[:5])
        errors.append(
            f"{len(closed)} contact(s) are Inactive and cannot be allocated ({names}). Reactivate them first."
        )
    non_active = [
        ch.contact
        for ch in changes
        if ch.to_caller and status_of.get(ch.contact.pk) not in CANNOT_ALLOCATE | CALLABLE_STATUSES
    ]
    if non_active:
        warnings.append(
            f"{len(non_active)} contact(s) are On Hold; they will not be called until their status is changed."
        )
    inactive_callers = {ch.to_caller for ch in changes if ch.to_caller and not ch.to_caller.is_active}
    for caller in inactive_callers:
        errors.append(f"{caller} is not an active user.")
    non_callers = {
        ch.to_caller
        for ch in changes
        if ch.to_caller and ch.to_caller.is_active and not ch.to_caller.is_caller
    }
    for caller in non_callers:
        warnings.append(f"{caller} does not have the Caller role.")
    before = {u.pk: n for u, n in caller_list_counts()}
    after = dict(before)
    for ch in changes:
        if ch.from_caller:
            after[ch.from_caller.pk] = after.get(ch.from_caller.pk, 0) - 1
        if ch.to_caller:
            after[ch.to_caller.pk] = after.get(ch.to_caller.pk, 0) + 1
    emptied = [pk for pk, n in after.items() if n == 0 and before.get(pk, 0) > 0]
    for user in User.objects.filter(pk__in=emptied):
        warnings.append(f"{user} will have no contacts after this change.")
    return errors, warnings


def count_changes(changes):
    """Before/after counts per caller touched by the plan, for the preview."""
    touched = {ch.from_caller for ch in changes if ch.from_caller} | {
        ch.to_caller for ch in changes if ch.to_caller
    }
    before = {u.pk: n for u, n in caller_list_counts()}
    rows = []
    for user in sorted(touched, key=str):
        out = sum(1 for ch in changes if ch.from_caller == user)
        incoming = sum(1 for ch in changes if ch.to_caller == user)
        rows.append(
            {
                "caller": user,
                "before": before.get(user.pk, 0),
                "out": out,
                "in": incoming,
                "after": before.get(user.pk, 0) - out + incoming,
            }
        )
    return rows


# --- Applying --------------------------------------------------------------


@transaction.atomic
def apply_plan(
    changes, *, kind, effective_date, actor, reason="", cycle=None, expected_fingerprint=None, sync=True
):
    from apps.calling.services import sync_contact_tasks

    if expected_fingerprint and expected_fingerprint != plan_fingerprint(changes):
        raise AllocationError(
            "Allocations changed since the preview. Review the new preview before applying."
        )
    errors, _ = check_plan(changes, effective_date)
    if errors:
        raise AllocationError(" ".join(errors))

    contact_ids = sorted(ch.contact.pk for ch in changes)
    if len(set(contact_ids)) != len(contact_ids):
        raise AllocationError("A contact appears more than once in the change set.")
    locked = {c.pk: c for c in Contact.objects.select_for_update().filter(pk__in=contact_ids).order_by("pk")}
    current = {
        a.contact_id: a for a in open_allocations().select_for_update().filter(contact_id__in=contact_ids)
    }

    operation = AllocationOperation.objects.create(
        kind=kind,
        effective_date=effective_date,
        reason=reason,
        cycle=cycle,
        performed_by=actor,
        change_count=len(changes),
    )
    moves = []
    for ch in changes:
        alloc = current.get(ch.contact.pk)
        if getattr(alloc, "caller_id", None) != getattr(ch.from_caller, "pk", None):
            raise AllocationError(f"{ch.contact} was reallocated by someone else; refresh the preview.")
        if alloc:
            alloc.effective_to = effective_date
            alloc.ended_by_operation = operation
            alloc.save(update_fields=["effective_to", "ended_by_operation"])
        if ch.to_caller:
            Allocation.objects.create(
                contact=locked[ch.contact.pk],
                caller=ch.to_caller,
                effective_from=effective_date,
                cycle=cycle,
                change_type=kind,
                reason=reason,
                operation=operation,
                created_by=actor,
            )
        moves.append(
            {
                "contact": ch.contact.pk,
                "from": getattr(ch.from_caller, "pk", None),
                "to": getattr(ch.to_caller, "pk", None),
            }
        )

    task_totals = {}
    if sync:
        for contact in locked.values():
            for key, n in sync_contact_tasks(contact, actor).items():
                task_totals[key] = task_totals.get(key, 0) + n
    operation.summary = {"moves": moves, "tasks": task_totals}
    operation.save(update_fields=["summary"])
    log_event(
        actor,
        "allocation.apply",
        f"{ChangeType(kind).label}: {len(changes)} contact(s) effective {effective_date}",
        operation,
        kind=kind,
        effective_date=effective_date,
        cycle=getattr(cycle, "pk", None),
        reason=reason,
        moves=moves,
        tasks=task_totals,
    )
    return operation


def assign_individual(contact, to_caller, *, effective_date, actor, reason, sync=True):
    changes = plan_assign([contact], to_caller)
    if not changes:
        raise AllocationError(f"{contact} is already allocated to {to_caller}.")
    return apply_plan(
        changes,
        kind=ChangeType.INDIVIDUAL,
        effective_date=effective_date,
        actor=actor,
        reason=reason,
        cycle=active_cycle(),
        sync=sync,
    )


def end_allocation(contact, *, effective_date, actor, reason):
    """Close the open allocation (Saint made Inactive). No-op if unallocated."""
    alloc = current_allocation(contact)
    if alloc is None:
        return None
    effective_date = max(effective_date, alloc.effective_from)
    return apply_plan(
        [PlannedChange(contact, alloc.caller, None)],
        kind=ChangeType.STATUS_CHANGE,
        effective_date=effective_date,
        actor=actor,
        reason=reason,
        sync=False,
    )


# --- Cycles ----------------------------------------------------------------


def default_cycle_dates(today=None):
    today = today or timezone.localdate()
    latest = AllocationCycle.objects.order_by("-planned_end_date").first()
    start = (
        latest.planned_end_date + timedelta(days=1) if latest and latest.planned_end_date >= today else today
    )
    end = add_months(start, settings.ALLOCATION_CYCLE_MONTHS) - timedelta(days=1)
    return start, end


def refresh_cycle_statuses(today=None):
    """Activate planned cycles whose start date has arrived and close the ones they replace."""
    today = today or timezone.localdate()
    due = AllocationCycle.objects.filter(status=CycleStatus.PLANNED, start_date__lte=today).order_by(
        "start_date"
    )
    for cycle in due:
        AllocationCycle.objects.filter(status=CycleStatus.ACTIVE, start_date__lt=cycle.start_date).update(
            status=CycleStatus.CLOSED
        )
        cycle.status = CycleStatus.ACTIVE
        cycle.save(update_fields=["status"])


def active_cycle():
    refresh_cycle_statuses()
    return AllocationCycle.objects.filter(status=CycleStatus.ACTIVE).order_by("-start_date").first()


@transaction.atomic
def create_cycle(*, name, start_date, planned_end_date, actor, notes=""):
    if planned_end_date < start_date:
        raise AllocationError("Planned end date must be on or after the start date.")
    overlapping = AllocationCycle.objects.exclude(status=CycleStatus.CLOSED).filter(start_date=start_date)
    if overlapping.exists():
        raise AllocationError("Another cycle already starts on that date.")
    cycle = AllocationCycle.objects.create(
        name=name, start_date=start_date, planned_end_date=planned_end_date, notes=notes, created_by=actor
    )
    refresh_cycle_statuses()
    cycle.refresh_from_db()
    log_event(
        actor,
        "allocation.cycle_create",
        f"Created cycle {cycle}",
        cycle,
        start_date=start_date,
        planned_end_date=planned_end_date,
    )
    return cycle


def rotation_due(today=None):
    """The active cycle if it ends within the reminder window (or has ended)."""
    today = today or timezone.localdate()
    cycle = active_cycle()
    if cycle and cycle.planned_end_date - today <= timedelta(days=settings.ROTATION_REMINDER_DAYS):
        return cycle
    return None
