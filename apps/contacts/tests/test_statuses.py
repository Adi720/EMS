"""Seva team rules: New for 6 months after registration, On Hold with a next call date."""

from datetime import date

import pytest
from django.urls import reverse

from apps.calling.models import TaskStatus
from apps.contacts.models import ContactStatus, StatusReason
from apps.contacts.services import change_status, initial_status, promote_new_saints

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 31)


def test_initial_status_depends_on_registration_date():
    assert initial_status(date(2026, 9, 1), today=TODAY) == ContactStatus.NEW
    assert initial_status(date(2026, 4, 30), today=TODAY) == ContactStatus.ACTIVE
    assert initial_status("2026-10-01", today=TODAY) == ContactStatus.NEW


def test_new_saints_are_called_and_become_active_after_six_months(
    make_contact, caller, allocate, make_session
):
    saint = make_contact(registration_date=date(2026, 9, 1))
    assert saint.status == ContactStatus.NEW
    allocate(saint, caller)
    task = make_session().tasks.get(contact=saint)
    assert task.status == TaskStatus.OPEN  # New Saints are on the call list

    assert promote_new_saints(date(2027, 2, 28)) == 0
    assert promote_new_saints(date(2027, 3, 1)) == 1
    saint.refresh_from_db()
    assert saint.status == ContactStatus.ACTIVE and saint.status_since == date(2027, 3, 1)
    change = saint.status_history.order_by("-pk").first()
    assert (change.from_status, change.to_status, change.reason_category) == (
        "new",
        "active",
        StatusReason.NEW_PERIOD_ENDED,
    )
    assert promote_new_saints(date(2027, 3, 2)) == 0


def test_on_hold_defaults_next_call_date_to_six_months(make_contact, coordinator):
    saint = make_contact()
    change_status(
        saint,
        ContactStatus.ON_HOLD,
        coordinator,
        reason_category=StatusReason.TEMPORARILY_AWAY,
        effective_date=date(2026, 11, 1),
    )
    saint.refresh_from_db()
    assert saint.review_date == date(2027, 5, 1)
    change_status(saint, ContactStatus.ACTIVE, coordinator, reason_category=StatusReason.AVAILABLE_AGAIN)
    saint.refresh_from_db()
    assert saint.review_date is None


def test_status_form_offers_new_statuses_and_hold_date(client, coordinator, make_contact):
    saint = make_contact(skills="Teaching", sewa="Stall")
    client.force_login(coordinator)
    page = client.get(reverse("contacts:detail", args=[saint.pk])).content.decode()
    assert "On Hold" in page and "Next call date" in page and "Do not call" not in page
    assert "Teaching" in page and "Stall" in page


def test_saints_list_promotes_due_new_saints(client, coordinator, make_contact):
    saint = make_contact(registration_date=date(2026, 4, 1))
    saint.status = ContactStatus.NEW
    saint.save()
    client.force_login(coordinator)
    client.get(reverse("contacts:list"))
    saint.refresh_from_db()
    assert saint.status == ContactStatus.ACTIVE
