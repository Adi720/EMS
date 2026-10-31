from datetime import date
from io import StringIO
from urllib.parse import unquote

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from apps.calling.models import EmsSession
from apps.calling.reminders import send_weekly_reminders

SATURDAY = date(2026, 10, 31)


@pytest.fixture
def callers_with_contacts(make_contact, caller, caller2, allocate):
    caller.email = "caller@example.org"
    caller.save()
    for _ in range(2):
        allocate(make_contact(), caller)
    allocate(make_contact(), caller2)  # caller2 has no email address
    return caller, caller2


def run(*args):
    out = StringIO()
    call_command("weekly_reminders", *args, stdout=out)
    return out.getvalue()


def test_does_nothing_on_other_days(callers_with_contacts):
    output = run("--date", "2026-10-29")  # Thursday
    assert "nothing to do" in output
    assert not EmsSession.objects.exists() and not mail.outbox


def test_saturday_starts_calling_and_emails_each_caller_once(callers_with_contacts, settings):
    settings.SITE_URL = "https://ems.example.org"
    caller, caller2 = callers_with_contacts
    output = run("--date", SATURDAY.isoformat())
    session = EmsSession.objects.get()
    assert session.session_date == date(2026, 11, 1) and session.is_open
    assert "Emailed: 1" in output and "No email address: Second Caller" in output
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["caller@example.org"]
    assert "EMS Congregation (1 Nov 2026)" in message.subject
    assert "2 contact(s)" in message.body and "https://ems.example.org/my-calls/" in message.body

    output = run("--date", SATURDAY.isoformat())  # e.g. the scheduler runs twice
    assert len(mail.outbox) == 1 and "Already reminded: Test Caller" in output


def test_without_auto_start_only_reminds_when_coordinator_started(
    callers_with_contacts, settings, coordinator
):
    settings.REMINDER_AUTO_START = False
    result = send_weekly_reminders(SATURDAY)
    assert result["session"] is None and not mail.outbox
    from apps.calling.services import start_weekly_calling

    start_weekly_calling(coordinator, today=SATURDAY)
    result = send_weekly_reminders(SATURDAY)
    assert len(result["sent"]) == 1 and len(mail.outbox) == 1


def test_dashboard_offers_whatsapp_share_once_calling_is_open(client, callers_with_contacts, coordinator):
    client.force_login(coordinator)
    assert "wa.me" not in client.get(reverse("core:coordinator_dashboard")).content.decode()
    client.post(reverse("calling:start_week"))
    response = client.get(reverse("core:coordinator_dashboard"))
    url = response.context["whatsapp_url"]
    assert url.startswith("https://wa.me/?text=")
    text = unquote(url.split("text=", 1)[1])
    session = EmsSession.objects.get()
    assert str(session) in text and "http://testserver/my-calls/" in text


def test_theme_toggle_is_on_every_page(client, caller):
    assert b'id="theme-toggle"' in client.get(reverse("accounts:login")).content
    client.force_login(caller)
    assert b'id="theme-toggle"' in client.get(reverse("core:caller_dashboard")).content
