"""Contact creation, editing and lifecycle changes.

Status changes are the only way ``Contact.status`` changes. Each one writes an
append-only ``ContactStatusChange`` row, closes or keeps the caller allocation,
and resynchronises call tasks in open sessions.
"""

from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import log_event
from apps.core.dates import add_months

from .models import CALLABLE_STATUSES, Contact, ContactStatus, ContactStatusChange, StatusReason

EDITABLE_FIELDS = [
    "full_name",
    "phone_primary",
    "phone_secondary",
    "area",
    "registration_date",
    "qualification",
    "collected_by_name",
    "skills",
    "sewa",
    "notes",
]

# Statuses that end the caller allocation (A-5). On Hold keeps it.
ENDS_ALLOCATION = {ContactStatus.INACTIVE}


def new_period_start(today=None):
    """Saints registered after this date are still New."""
    return add_months(today or timezone.localdate(), -settings.NEW_PERIOD_MONTHS)


def initial_status(registration_date, today=None):
    """New for the first NEW_PERIOD_MONTHS after meeting them at the stall, then Active."""
    if isinstance(registration_date, str):
        registration_date = date.fromisoformat(registration_date[:10])
    if registration_date and registration_date > new_period_start(today):
        return ContactStatus.NEW
    return ContactStatus.ACTIVE


def default_hold_until(today=None):
    return add_months(today or timezone.localdate(), settings.ON_HOLD_MONTHS)


class LifecycleError(Exception):
    pass


def find_possible_duplicates(phones, exclude_pk=None):
    """Contacts sharing any of the given normalised phone numbers."""
    phones = [p for p in phones if p]
    if not phones:
        return Contact.objects.none()
    qs = Contact.objects.filter(Q(phone_primary__in=phones) | Q(phone_secondary__in=phones))
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.order_by("full_name")


@transaction.atomic
def create_contact(data, actor, *, reason=StatusReason.CREATED, reason_text="", legacy_data=None):
    contact = Contact(
        **{field: data.get(field, "") for field in EDITABLE_FIELDS},
        status=initial_status(data.get("registration_date")),
        status_since=timezone.localdate(),
        legacy_data=legacy_data or {},
        created_by=actor,
        updated_by=actor,
    )
    contact.full_clean()
    contact.save()
    ContactStatusChange.objects.create(
        contact=contact,
        from_status="",
        to_status=contact.status,
        reason_category=reason,
        reason_text=reason_text,
        effective_date=contact.status_since,
        changed_by=actor,
    )
    details = {"added_by": contact.collected_by_name} if contact.collected_by_name else {}
    log_event(actor, "contact.create", f"Created contact {contact}", contact, **details)
    return contact


@transaction.atomic
def update_contact(contact, data, actor):
    changed = [f for f in EDITABLE_FIELDS if f in data and getattr(contact, f) != data[f]]
    if not changed:
        return contact, []
    for field in changed:
        setattr(contact, field, data[field])
    contact.updated_by = actor
    contact.full_clean()
    contact.save()
    # Field names only: values (phones) are kept out of the audit log.
    log_event(actor, "contact.update", f"Edited contact {contact}", contact, fields=changed)
    return contact, changed


@transaction.atomic
def change_status(
    contact,
    new_status,
    actor,
    *,
    reason_category,
    reason_text="",
    effective_date=None,
    review_date=None,
    reactivation_caller=None,
):
    from apps.allocations import services as allocation_services
    from apps.calling.services import sync_contact_tasks

    contact = Contact.objects.select_for_update().get(pk=contact.pk)
    effective_date = effective_date or timezone.localdate()
    old_status = contact.status

    if new_status not in ContactStatus.values:
        raise LifecycleError("Unknown status.")
    if new_status == old_status:
        raise LifecycleError(f"Contact is already {contact.get_status_display()}.")
    if new_status == ContactStatus.ON_HOLD:
        review_date = review_date or default_hold_until(effective_date)
    else:
        review_date = None

    ContactStatusChange.objects.create(
        contact=contact,
        from_status=old_status,
        to_status=new_status,
        reason_category=reason_category,
        reason_text=reason_text,
        effective_date=effective_date,
        review_date=review_date,
        changed_by=actor,
    )
    contact.status = new_status
    contact.status_since = effective_date
    contact.review_date = review_date
    contact.updated_by = actor
    contact.save()

    if new_status in ENDS_ALLOCATION:
        allocation_services.end_allocation(
            contact,
            effective_date=effective_date,
            actor=actor,
            reason=f"Status: {contact.get_status_display()}",
        )
    elif new_status in CALLABLE_STATUSES and reactivation_caller is not None:
        if allocation_services.current_allocation(contact) is None:
            allocation_services.assign_individual(
                contact,
                reactivation_caller,
                effective_date=effective_date,
                actor=actor,
                reason="Reactivated",
                sync=False,
            )

    task_changes = sync_contact_tasks(contact, actor)
    log_event(
        actor,
        "contact.status_change",
        f"{contact}: {ContactStatus(old_status).label} → {contact.get_status_display()}",
        contact,
        from_status=old_status,
        to_status=new_status,
        reason_category=reason_category,
        effective_date=effective_date,
        tasks=task_changes,
    )
    return contact


@transaction.atomic
def promote_new_saints(today=None):
    """New Saints whose registration date is NEW_PERIOD_MONTHS ago become Active.
    Safe to call often (dashboard, Saints list, starting calling, the daily job)."""
    today = today or timezone.localdate()
    due = list(
        Contact.objects.select_for_update().filter(
            status=ContactStatus.NEW, registration_date__lte=new_period_start(today)
        )
    )
    for contact in due:
        ContactStatusChange.objects.create(
            contact=contact,
            from_status=ContactStatus.NEW,
            to_status=ContactStatus.ACTIVE,
            reason_category=StatusReason.NEW_PERIOD_ENDED,
            reason_text=f"{settings.NEW_PERIOD_MONTHS} months since registration",
            effective_date=today,
        )
    if due:
        Contact.objects.filter(pk__in=[c.pk for c in due]).update(
            status=ContactStatus.ACTIVE, status_since=today
        )
        log_event(None, "contact.new_period_ended", f"{len(due)} New Saint(s) are now Active", count=len(due))
    return len(due)


def deletable(contacts):
    """Split contacts into (can delete, kept). A Saint with recorded call results is kept so
    past congregation reports stay correct; mark them Inactive instead."""
    from apps.calling.models import CallAttempt

    with_calls = set(
        CallAttempt.objects.filter(task__contact__in=contacts).values_list("task__contact_id", flat=True)
    )
    can, kept = [], []
    for contact in contacts:
        (kept if contact.pk in with_calls else can).append(contact)
    return can, kept


@transaction.atomic
def delete_contacts(contacts, actor, reason=""):
    """Permanently delete Saints that have no call results, with their caller assignments,
    status history and not-yet-called list entries. Returns the names deleted."""
    from apps.allocations.models import Allocation
    from apps.calling.models import CallTask
    from apps.imports.models import ImportRow

    contacts = list(Contact.objects.select_for_update().filter(pk__in=[c.pk for c in contacts]))
    can, kept = deletable(contacts)
    if kept:
        raise LifecycleError(
            "These Saints have call results and cannot be deleted: "
            + ", ".join(c.full_name for c in kept)
            + ". Change their status to Inactive instead."
        )
    ids = [c.pk for c in can]
    # Bulk deletes on purpose: the history models refuse instance.delete() in normal use.
    CallTask.objects.filter(contact_id__in=ids).delete()
    Allocation.objects.filter(contact_id__in=ids).delete()
    ContactStatusChange.objects.filter(contact_id__in=ids).delete()
    ImportRow.objects.filter(contact_id__in=ids).update(contact=None)
    ImportRow.objects.filter(link_contact_id__in=ids).update(link_contact=None)
    names = [c.full_name for c in can]
    for contact in can:
        log_event(
            actor,
            "contact.delete",
            f"Deleted Saint {contact.full_name}",
            contact,
            area=contact.area,
            reason=reason,
        )
    Contact.objects.filter(pk__in=ids).delete()
    return names
