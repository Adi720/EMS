"""In-app caller management: what coordinators may and may not do."""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.allocations.models import ChangeType
from apps.allocations.services import current_allocation, unallocated_active_contacts
from apps.audit.models import AuditEvent
from apps.calling.models import Outcome, TaskStatus

NEW_CALLER = {
    "first_name": "Nisha",
    "last_name": "Synthetic",
    "username": "nisha.synth",
    "email": "nisha@example.org",
    "password1": "Synthetic-pass-2026!",
    "password2": "Synthetic-pass-2026!",
}


@pytest.fixture
def coord_client(client, coordinator):
    client.force_login(coordinator)
    return client


def test_coordinator_creates_caller_only_account(coord_client, client):
    response = coord_client.post(reverse("team:create"), NEW_CALLER)
    assert response.status_code == 302
    user = User.objects.get(username="nisha.synth")
    assert set(user.groups.values_list("name", flat=True)) == {Role.CALLER}
    assert not user.is_staff and not user.is_superuser and user.is_caller and not user.is_coordinator
    assert user.check_password(NEW_CALLER["password1"])
    event = AuditEvent.objects.get(action="team.create")
    assert NEW_CALLER["password1"] not in str(event.details) + event.summary
    client.logout()
    client.post(reverse("accounts:login"), {"username": "nisha.synth", "password": NEW_CALLER["password1"]})
    assert client.get(reverse("core:caller_dashboard")).status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password2", "different-pass-2026!"),
        ("password1", "short"),
        ("username", "caller"),
        ("first_name", ""),
    ],
)
def test_create_validation(coord_client, caller, field, value):
    data = {**NEW_CALLER, field: value}
    if field == "password1":
        data["password2"] = value
    response = coord_client.post(reverse("team:create"), data)
    assert response.status_code == 200 and response.context["form"].errors
    assert not User.objects.filter(username=data["username"], first_name="Nisha").exists()


def test_create_form_cannot_grant_privileges(coord_client):
    coord_client.post(
        reverse("team:create"), {**NEW_CALLER, "is_superuser": "on", "is_staff": "on", "groups": "1"}
    )
    user = User.objects.get(username="nisha.synth")
    assert not user.is_superuser and not user.is_staff
    assert not user.groups.filter(name=Role.COORDINATOR).exists()


def test_coordinator_cannot_manage_coordinators_or_admins(coord_client, caller_coordinator, sysadmin):
    sysadmin.groups.add(*User.objects.get(pk=caller_coordinator.pk).groups.all())  # an admin who also calls
    for target in (caller_coordinator, sysadmin):
        assert coord_client.get(reverse("team:detail", args=[target.pk])).status_code == 200  # may view
        for url in (reverse("team:edit", args=[target.pk]), reverse("team:password", args=[target.pk])):
            assert coord_client.get(url).status_code == 403
        assert coord_client.post(reverse("team:active", args=[target.pk, "deactivate"])).status_code == 403
        target.refresh_from_db()
        assert target.is_active


def test_callers_cannot_use_team_pages(client, caller, caller2):
    client.force_login(caller)
    for url in (
        reverse("team:list"),
        reverse("team:create"),
        reverse("team:detail", args=[caller2.pk]),
        reverse("team:edit", args=[caller2.pk]),
    ):
        assert client.get(url).status_code == 403
    assert client.post(reverse("team:active", args=[caller2.pk, "deactivate"])).status_code == 403
    caller2.refresh_from_db()
    assert caller2.is_active


def test_edit_and_reset_password(coord_client, caller, client):
    response = coord_client.post(
        reverse("team:edit", args=[caller.pk]),
        {"first_name": "Renamed", "last_name": "Caller", "email": "new@example.org"},
    )
    assert response.status_code == 302
    caller.refresh_from_db()
    assert (caller.first_name, caller.email) == ("Renamed", "new@example.org")
    response = coord_client.post(
        reverse("team:password", args=[caller.pk]),
        {"new_password1": "Fresh-synthetic-77", "new_password2": "Fresh-synthetic-77"},
    )
    assert response.status_code == 302
    caller.refresh_from_db()
    assert caller.check_password("Fresh-synthetic-77")
    assert AuditEvent.objects.filter(action="team.password_reset").exists()
    weak = coord_client.post(
        reverse("team:password", args=[caller.pk]), {"new_password1": "123", "new_password2": "123"}
    )
    assert weak.status_code == 200 and weak.context["form"].errors


def test_deactivation_leaves_saints_unassigned_and_keeps_history(
    coord_client, caller, make_contact, allocate, make_session, record
):
    saints = [make_contact() for _ in range(2)]
    for contact in saints:
        allocate(contact, caller)
    session = make_session()
    attempted, untouched = (session.tasks.get(contact=c) for c in saints)
    record(attempted, Outcome.YES)

    response = coord_client.post(reverse("team:active", args=[caller.pk, "deactivate"]))
    assert response.status_code == 302
    caller.refresh_from_db()
    assert not caller.is_active
    assert all(current_allocation(c) is None for c in saints)
    assert set(unallocated_active_contacts()) == set(saints)
    assert caller.allocations.filter(change_type__in=[ChangeType.INDIVIDUAL]).count() == 2  # history kept
    attempted.refresh_from_db()
    untouched.refresh_from_db()
    assert attempted.status == TaskStatus.OPEN and attempted.caller == caller  # credit kept
    assert untouched.status == TaskStatus.WITHDRAWN

    coord_client.post(reverse("team:active", args=[caller.pk, "activate"]))
    caller.refresh_from_db()
    assert caller.is_active and current_allocation(saints[0]) is None  # Saints are not silently restored


def test_deactivated_caller_cannot_log_in(coord_client, caller):
    from django.test import Client

    coord_client.post(reverse("team:active", args=[caller.pk, "deactivate"]))
    browser = Client()  # a separate browser, not the coordinator's session
    browser.post(reverse("accounts:login"), {"username": "caller", "password": "Synthetic-pass-2026"})
    assert "_auth_user_id" not in browser.session


def test_team_list_and_detail_render(coord_client, caller, make_contact, allocate):
    allocate(make_contact(), caller)
    response = coord_client.get(reverse("team:list"))
    assert response.status_code == 200
    row = next(r for r in response.context["rows"] if r["user"] == caller)
    assert row["saints"] == 1 and row["manageable"]
    assert coord_client.get(reverse("team:detail", args=[caller.pk])).status_code == 200
