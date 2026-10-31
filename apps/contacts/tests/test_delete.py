"""Coordinators and admins can delete Saints that have no call results."""

import pytest
from django.urls import reverse

from apps.allocations.models import Allocation
from apps.audit.models import AuditEvent
from apps.calling.models import CallTask, Outcome
from apps.contacts.models import Contact, ContactStatusChange
from apps.contacts.services import LifecycleError, delete_contacts

pytestmark = pytest.mark.django_db


def test_delete_removes_saint_and_its_records(
    client, coordinator, caller, make_contact, allocate, make_session
):
    saint = make_contact(full_name="Added Twice")
    allocate(saint, caller)
    make_session()  # puts the Saint on this week's call list, not yet called
    assert CallTask.objects.filter(contact=saint).exists()

    client.force_login(coordinator)
    page = client.get(reverse("contacts:delete") + f"?ids={saint.pk}")
    assert page.status_code == 200 and "Added Twice" in page.content.decode()

    response = client.post(reverse("contacts:delete"), {"ids": [saint.pk], "reason": "duplicate"})
    assert response.status_code == 302 and response.url == reverse("contacts:list")
    assert not Contact.objects.filter(pk=saint.pk).exists()
    assert not Allocation.objects.filter(contact_id=saint.pk).exists()
    assert not ContactStatusChange.objects.filter(contact_id=saint.pk).exists()
    assert not CallTask.objects.filter(contact_id=saint.pk).exists()
    event = AuditEvent.objects.get(action="contact.delete")
    assert event.actor == coordinator and event.details["reason"] == "duplicate"
    audit = client.get(reverse("audit:event_list")).content.decode()
    assert "Deleted a Saint" in audit


def test_bulk_delete_keeps_saints_with_call_results(
    client, coordinator, caller, make_contact, allocate, make_session, record
):
    called, fresh = make_contact(full_name="Already Called"), make_contact(full_name="Never Called")
    allocate(called, caller)
    session = make_session()
    record(session.tasks.get(contact=called), Outcome.YES)

    client.force_login(coordinator)
    page = client.get(reverse("contacts:delete"), {"ids": [called.pk, fresh.pk]}).content.decode()
    assert "Kept — already called" in page and "Delete 1 Saint" in page

    client.post(reverse("contacts:delete"), {"ids": [called.pk, fresh.pk]})
    assert Contact.objects.filter(pk=called.pk).exists()
    assert not Contact.objects.filter(pk=fresh.pk).exists()

    with pytest.raises(LifecycleError, match="call results"):
        delete_contacts([called], coordinator)


def test_admin_can_delete_and_returns_to_the_filtered_list(client, admin_user, make_contact):
    saint = make_contact()
    client.force_login(admin_user)
    back = reverse("contacts:list") + "?status=active"
    response = client.post(reverse("contacts:delete"), {"ids": [saint.pk], "next": back})
    assert response.url == back and not Contact.objects.exists()


def test_next_cannot_point_off_site(client, coordinator, make_contact):
    saint = make_contact()
    client.force_login(coordinator)
    response = client.post(
        reverse("contacts:delete"), {"ids": [saint.pk], "next": "https://evil.example/contacts/"}
    )
    assert response.url == reverse("contacts:list")


@pytest.mark.parametrize("fixture", ["caller", "no_role_user"])
def test_callers_cannot_delete(client, request, make_contact, fixture):
    saint = make_contact()
    client.force_login(request.getfixturevalue(fixture))
    assert client.get(reverse("contacts:delete") + f"?ids={saint.pk}").status_code == 403
    assert client.post(reverse("contacts:delete"), {"ids": [saint.pk]}).status_code == 403
    assert Contact.objects.filter(pk=saint.pk).exists()


def test_get_never_deletes(client, coordinator, make_contact):
    saint = make_contact()
    client.force_login(coordinator)
    client.get(reverse("contacts:delete") + f"?ids={saint.pk}")
    assert Contact.objects.filter(pk=saint.pk).exists()
