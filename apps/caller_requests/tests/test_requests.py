"""Callers raise requests about their Saints; coordinators approve or reject them."""

import pytest
from django.core import mail
from django.urls import reverse

from apps.caller_requests.models import CallerRequest, RequestKind, RequestStatus
from apps.caller_requests.services import RequestError, decide, raise_request
from apps.calling.models import TaskStatus
from apps.contacts.models import ContactStatus
from apps.contacts.services import delete_contacts

pytestmark = pytest.mark.django_db


@pytest.fixture
def my_saint(make_contact, allocate, caller):
    saint = make_contact(full_name="Unable Saint")
    allocate(saint, caller)
    return saint


def test_caller_raises_request_and_coordinator_is_notified(client, caller, coordinator, my_saint):
    coordinator.email = "coordinator@example.org"
    coordinator.save()
    client.force_login(caller)
    page = client.get(reverse("caller_requests:mine") + f"?contact={my_saint.pk}").content.decode()
    assert "Unable Saint" in page and "Please type your remarks" in page

    response = client.post(
        reverse("caller_requests:mine"),
        {"kind": RequestKind.UNABLE_TO_ATTEND, "contact": my_saint.pk, "reason": "Moved to Pune"},
    )
    assert response.status_code == 302
    request = CallerRequest.objects.get()
    assert request.raised_by == caller and request.contact == my_saint and request.is_pending

    client.force_login(coordinator)
    dashboard = client.get(reverse("core:coordinator_dashboard")).content.decode()
    assert "1 request" in dashboard and "Requests" in dashboard
    manage = client.get(reverse("caller_requests:manage")).content.decode()
    assert "Moved to Pune" in manage and "Unable Saint" in manage


def test_email_goes_to_coordinators_with_an_address(
    caller, coordinator, my_saint, django_capture_on_commit_callbacks
):
    coordinator.email = "coordinator@example.org"
    coordinator.save()
    with django_capture_on_commit_callbacks(execute=True):
        raise_request(caller, RequestKind.WRONG_NUMBER, "Number not in use", my_saint)
    assert mail.outbox and mail.outbox[0].to == ["coordinator@example.org"]
    assert "Wrong or changed mobile number" in mail.outbox[0].subject


def test_approving_unable_to_attend_makes_saint_inactive(caller, coordinator, my_saint, make_session):
    task = make_session().tasks.get(contact=my_saint)
    request = raise_request(caller, RequestKind.UNABLE_TO_ATTEND, "Works on Sundays", my_saint)
    decide(request, coordinator, approve=True, note="Thank you")
    my_saint.refresh_from_db()
    task.refresh_from_db()
    assert my_saint.status == ContactStatus.INACTIVE
    assert task.status == TaskStatus.WITHDRAWN
    change = my_saint.status_history.order_by("-pk").first()
    assert "Works on Sundays" in change.reason_text
    request.refresh_from_db()
    assert request.status == RequestStatus.APPROVED and request.decision_note == "Thank you"
    with pytest.raises(RequestError):
        decide(request, coordinator, approve=False)


def test_rejecting_changes_nothing(client, caller, coordinator, my_saint):
    request = raise_request(caller, RequestKind.UNABLE_TO_ATTEND, "Not sure", my_saint)
    client.force_login(coordinator)
    client.post(
        reverse("caller_requests:decide", args=[request.pk, "reject"]), {"note": "Please try once more"}
    )
    my_saint.refresh_from_db()
    request.refresh_from_db()
    assert my_saint.status == ContactStatus.ACTIVE and request.status == RequestStatus.REJECTED
    client.force_login(caller)
    assert "Please try once more" in client.get(reverse("caller_requests:mine")).content.decode()


def test_callers_only_raise_requests_about_their_own_saints(caller, caller2, make_contact, allocate):
    other = make_contact()
    allocate(other, caller2)
    with pytest.raises(RequestError, match="Saints you call"):
        raise_request(caller, RequestKind.UNABLE_TO_ATTEND, "x", other)
    with pytest.raises(RequestError, match="Choose the Saint"):
        raise_request(caller, RequestKind.UNABLE_TO_ATTEND, "x")
    assert raise_request(caller, RequestKind.OTHER, "Need help with the app").contact is None


def test_duplicate_waiting_request_is_refused(caller, my_saint):
    raise_request(caller, RequestKind.UNABLE_TO_ATTEND, "x", my_saint)
    with pytest.raises(RequestError, match="already"):
        raise_request(caller, RequestKind.UNABLE_TO_ATTEND, "again", my_saint)


def test_callers_cannot_decide(client, caller, my_saint):
    request = raise_request(caller, RequestKind.OTHER, "x")
    client.force_login(caller)
    assert client.get(reverse("caller_requests:manage")).status_code == 403
    assert client.post(reverse("caller_requests:decide", args=[request.pk, "approve"])).status_code == 403
    request.refresh_from_db()
    assert request.is_pending


def test_deleting_saint_keeps_request_with_name(caller, coordinator, make_contact, allocate):
    saint = make_contact(full_name="Added Twice")
    allocate(saint, caller)
    request = raise_request(caller, RequestKind.OTHER, "Duplicate entry", saint)
    delete_contacts([saint], coordinator)
    request.refresh_from_db()
    assert request.contact is None and request.contact_name == "Added Twice"
