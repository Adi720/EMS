from datetime import date

import pytest
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from apps.allocations import services
from apps.allocations.models import Allocation, AllocationCycle, ChangeType
from apps.audit.models import AuditEvent
from conftest import ALLOCATION_START


def lists(*callers):
    return {
        c.username: sorted(a.contact_id for a in services.open_allocations().filter(caller=c))
        for c in callers
    }


def test_reassignment_closes_previous_and_keeps_history(make_contact, caller, caller2, allocate):
    contact = make_contact(registration_date=date(2024, 5, 5))
    allocate(contact, caller)
    allocate(contact, caller2, effective_date=date(2026, 4, 1), reason="Rotation")
    first, second = contact.allocations.order_by("effective_from")
    assert (first.caller, first.effective_from, first.effective_to) == (
        caller,
        ALLOCATION_START,
        date(2026, 4, 1),
    )
    assert (second.caller, second.effective_from, second.effective_to) == (caller2, date(2026, 4, 1), None)
    assert second.reason == "Rotation" and second.change_type == ChangeType.INDIVIDUAL
    assert second.created_by.username == "coordinator"
    assert first.ended_by_operation == second.operation
    assert services.allocation_on(contact, date(2026, 3, 31)).caller == caller
    assert services.allocation_on(contact, date(2026, 4, 1)).caller == caller2
    assert AuditEvent.objects.filter(action="allocation.apply").count() == 2


def test_backdating_before_current_start_is_rejected(make_contact, caller, caller2, allocate):
    contact = make_contact()
    allocate(contact, caller, effective_date=date(2026, 5, 1))
    with pytest.raises(services.AllocationError):
        allocate(contact, caller2, effective_date=date(2026, 4, 1))
    assert contact.allocations.count() == 1


def test_move_all_swap_and_rotate(make_contact, make_user, caller, caller2, allocate, coordinator):
    caller3 = make_user("caller3", ["Caller"], first_name="Third")
    a = [make_contact() for _ in range(3)]
    b = [make_contact() for _ in range(2)]
    c = [make_contact()]
    for contact in a:
        allocate(contact, caller)
    for contact in b:
        allocate(contact, caller2)
    allocate(c[0], caller3)
    ids = lambda contacts: sorted(x.pk for x in contacts)  # noqa: E731
    apply = lambda changes, kind: services.apply_plan(  # noqa: E731
        changes, kind=kind, effective_date=date(2026, 4, 1), actor=coordinator, reason="rotation"
    )

    apply(services.plan_swap(caller, caller2), ChangeType.SWAP)
    assert lists(caller, caller2) == {"caller": ids(b), "caller2": ids(a)}

    apply(services.plan_rotate([caller, caller2, caller3]), ChangeType.ROTATE)
    assert lists(caller, caller2, caller3) == {"caller": ids(c), "caller2": ids(b), "caller3": ids(a)}

    apply(services.plan_move_all(caller3, caller), ChangeType.MOVE_ALL)
    assert lists(caller, caller3) == {"caller": ids(a + c), "caller3": []}


def test_apply_is_atomic_when_a_contact_changed_since_preview(
    make_contact, caller, caller2, allocate, coordinator
):
    contacts = [make_contact() for _ in range(3)]
    for contact in contacts:
        allocate(contact, caller)
    plan = services.plan_assign(contacts, caller2)
    allocate(contacts[2], caller2, effective_date=date(2026, 2, 1))  # someone else moved one meanwhile
    with pytest.raises(services.AllocationError):
        services.apply_plan(plan, kind=ChangeType.ASSIGN, effective_date=date(2026, 3, 1), actor=coordinator)
    assert lists(caller)["caller"] == sorted(c.pk for c in contacts[:2])
    assert Allocation.objects.filter(effective_from=date(2026, 3, 1)).count() == 0


def test_fingerprint_mismatch_is_rejected(make_contact, caller, caller2, allocate, coordinator):
    contact = make_contact()
    allocate(contact, caller)
    plan = services.plan_assign([contact], caller2)
    with pytest.raises(services.AllocationError):
        services.apply_plan(
            plan,
            kind=ChangeType.ASSIGN,
            effective_date=date(2026, 3, 1),
            actor=coordinator,
            expected_fingerprint="stale",
        )


def test_database_allows_only_one_open_allocation(make_contact, caller, caller2, allocate):
    contact = make_contact()
    allocate(contact, caller)
    with pytest.raises(IntegrityError), transaction.atomic():
        Allocation.objects.create(
            contact=contact, caller=caller2, effective_from=date(2026, 6, 1), change_type=ChangeType.ASSIGN
        )


def test_database_rejects_end_before_start(make_contact, caller):
    with pytest.raises(IntegrityError), transaction.atomic():
        Allocation.objects.create(
            contact=make_contact(),
            caller=caller,
            effective_from=date(2026, 6, 1),
            effective_to=date(2026, 5, 1),
            change_type=ChangeType.ASSIGN,
        )


@pytest.mark.skipif(connection.vendor != "postgresql", reason="exclusion constraint is PostgreSQL-only")
def test_postgres_rejects_overlapping_closed_ranges(make_contact, caller, caller2):
    contact = make_contact()
    Allocation.objects.create(
        contact=contact,
        caller=caller,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 4, 1),
        change_type=ChangeType.ASSIGN,
    )
    Allocation.objects.create(
        contact=contact,
        caller=caller2,
        effective_from=date(2026, 4, 1),
        effective_to=date(2026, 7, 1),
        change_type=ChangeType.ASSIGN,
    )  # adjacent is fine
    with pytest.raises(IntegrityError), transaction.atomic():
        Allocation.objects.create(
            contact=contact,
            caller=caller2,
            effective_from=date(2026, 3, 1),
            effective_to=date(2026, 5, 1),
            change_type=ChangeType.ASSIGN,
        )


def test_unallocated_includes_never_allocated_and_ended_allocations(
    make_contact, caller, allocate, coordinator
):
    never = make_contact()
    current = make_contact()
    allocate(current, caller)
    ended = make_contact()
    allocate(ended, caller)
    services.end_allocation(ended, effective_date=date(2026, 6, 1), actor=coordinator, reason="test")
    assert set(services.unallocated_active_contacts()) == {never, ended}


# --- Views -------------------------------------------------------------------------


@pytest.fixture
def coord_client(client, coordinator):
    client.force_login(coordinator)
    return client


def test_bulk_preview_changes_nothing_then_apply(coord_client, make_contact, caller, caller2, allocate):
    contacts = [make_contact() for _ in range(2)]
    for contact in contacts:
        allocate(contact, caller)
    data = {
        "kind": "swap",
        "caller_a": caller.pk,
        "caller_b": caller2.pk,
        "effective_date": "2026-04-01",
        "reason": "Quarterly rotation",
        "action": "preview",
    }
    response = coord_client.post(reverse("allocations:change"), data)
    assert response.status_code == 200
    assert len(response.context["changes"]) == 2
    assert lists(caller2)["caller2"] == []  # preview only

    response = coord_client.post(
        reverse("allocations:change"),
        {**data, "action": "apply", "fingerprint": response.context["fingerprint"]},
    )
    assert response.status_code == 302
    assert lists(caller2)["caller2"] == sorted(c.pk for c in contacts)


def test_bulk_assign_selected_unallocated(coord_client, make_contact, caller):
    contacts = [make_contact() for _ in range(3)]
    data = {
        "kind": "assign",
        "contacts": [c.pk for c in contacts[:2]],
        "to_caller": caller.pk,
        "effective_date": "2026-04-01",
        "reason": "New contacts",
        "action": "preview",
    }
    preview = coord_client.post(reverse("allocations:change"), data)
    coord_client.post(
        reverse("allocations:change"),
        {**data, "action": "apply", "fingerprint": preview.context["fingerprint"]},
    )
    assert lists(caller)["caller"] == sorted(c.pk for c in contacts[:2])
    assert services.current_allocation(contacts[2]) is None


def test_allocation_pages_are_coordinator_only(client, caller):
    client.force_login(caller)
    for name in ["allocations:home", "allocations:change", "allocations:cycle_create"]:
        assert client.get(reverse(name)).status_code == 403
    assert client.post(reverse("allocations:change"), {"kind": "swap"}).status_code == 403


# --- Cycles -----------------------------------------------------------------------


def test_cycle_defaults_to_three_months_and_activates(coordinator):
    start, end = services.default_cycle_dates(today=date(2026, 1, 15))
    assert (start, end) == (date(2026, 1, 15), date(2026, 4, 14))
    cycle = services.create_cycle(
        name="Q1", start_date=date(2026, 1, 1), planned_end_date=date(2026, 3, 31), actor=coordinator
    )
    assert cycle.status == "active"
    nxt = services.create_cycle(
        name="Q2", start_date=date(2026, 4, 1), planned_end_date=date(2026, 6, 30), actor=coordinator
    )
    assert AllocationCycle.objects.get(pk=cycle.pk).status == "closed"
    assert nxt.status == "active"
    assert services.rotation_due(today=date(2026, 6, 20)) == nxt
    assert services.rotation_due(today=date(2026, 5, 1)) is None
