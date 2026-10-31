"""Stall Lead login (adds Saints only) and Forgot password by email."""

import re
from datetime import date
from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.audit.models import AuditEvent
from apps.contacts.models import Contact, ContactStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def stall(make_user):
    return make_user("stall.sewa.admin", [Role.STALL_LEAD])


def saint_data(**extra):
    return {
        "full_name": "Stall Saint",
        "phone_primary": "98765 43219",
        "area": "Riverside",
        "registration_date": "2026-10-25",
        "skills": "Music",
        "collected_by_name": "Ravi Kumar",
        **extra,
    }


def test_stall_lead_adds_a_new_saint_without_caller(client, stall):
    client.force_login(stall)
    assert client.get(reverse("core:home")).url == reverse("contacts:stall_add")
    page = client.get(reverse("contacts:stall_add")).content.decode()
    assert "Your name" in page and "Caller" not in page.split("<form")[1].split("</form>")[0]

    missing_name = client.post(reverse("contacts:stall_add"), saint_data(collected_by_name=""))
    assert missing_name.status_code == 200 and not Contact.objects.exists()

    response = client.post(reverse("contacts:stall_add"), saint_data())
    assert response.status_code == 302
    saint = Contact.objects.get()
    assert saint.collected_by_name == "Ravi Kumar" and saint.skills == "Music"
    assert saint.status == ContactStatus.NEW and not saint.allocations.exists()
    event = AuditEvent.objects.get(action="contact.create")
    assert event.actor == stall and event.details["added_by"] == "Ravi Kumar"
    assert "Stall Saint" in client.get(reverse("contacts:stall_add")).content.decode()


def test_stall_lead_duplicate_check_hides_other_saints(client, stall, make_contact):
    make_contact(full_name="Existing Person", phone="+919876543219")
    client.force_login(stall)
    page = client.post(reverse("contacts:stall_add"), saint_data()).content.decode()
    assert "already in the Saints list" in page and "Existing Person" not in page
    client.post(reverse("contacts:stall_add"), saint_data(confirm_duplicate="on"))
    assert Contact.objects.count() == 2


@pytest.mark.parametrize(
    "name",
    ["contacts:list", "core:coordinator_dashboard", "core:caller_dashboard", "allocations:home", "team:list"],
)
def test_stall_lead_cannot_see_anything_else(client, stall, name):
    client.force_login(stall)
    assert client.get(reverse(name)).status_code == 403


def test_callers_cannot_use_the_stall_page(client, caller):
    client.force_login(caller)
    assert client.get(reverse("contacts:stall_add")).status_code == 403


def test_create_stall_lead_command():
    out = StringIO()
    call_command("create_stall_lead", stdout=out)
    user = User.objects.get(username="stall.sewa.admin")
    password = re.search(r"Password \(shown only now\): (\S+)", out.getvalue()).group(1)
    assert user.is_stall_lead and user.check_password(password) and not user.is_staff
    with pytest.raises(Exception, match="already exists"):
        call_command("create_stall_lead", stdout=StringIO())
    call_command("create_stall_lead", "--reset-password", stdout=StringIO())
    user.refresh_from_db()
    assert not user.check_password(password)


def test_forgot_password_by_email(client, caller):
    caller.email = "caller@example.org"
    caller.save()
    response = client.post(reverse("accounts:password_reset"), {"email": "caller@example.org"})
    assert response.status_code == 302 and len(mail.outbox) == 1
    link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)
    path = link.split("testserver", 1)[1]
    form_page = client.get(path, follow=True)
    assert form_page.context["validlink"]
    client.post(
        form_page.redirect_chain[-1][0],
        {"new_password1": "Fresh-password-2026", "new_password2": "Fresh-password-2026"},
    )
    caller.refresh_from_db()
    assert caller.check_password("Fresh-password-2026")


def test_forgot_password_does_not_reveal_unknown_emails(client):
    response = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.org"})
    assert response.status_code == 302 and not mail.outbox


def test_login_page_links_to_forgot_password(client):
    assert reverse("accounts:password_reset") in client.get(reverse("accounts:login")).content.decode()


def test_new_status_from_stall_date(client, stall):
    client.force_login(stall)
    client.post(reverse("contacts:stall_add"), saint_data(registration_date="2025-01-05"))
    assert Contact.objects.get().status == ContactStatus.ACTIVE  # met long ago
    assert date(2025, 1, 5) == Contact.objects.get().registration_date
