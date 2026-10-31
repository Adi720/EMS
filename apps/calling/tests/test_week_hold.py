"""No Calling Sewa this week: nothing can start or be recorded, callers see a notice."""

import pytest
from django.core import mail
from django.urls import reverse

from apps.calling import services
from apps.calling.models import EmsSession, Outcome
from apps.calling.reminders import send_weekly_reminders

pytestmark = pytest.mark.django_db


@pytest.fixture
def week(make_contact, allocate, caller):
    saint = make_contact(full_name="Week Saint")
    allocate(saint, caller)
    return saint


def test_hold_blocks_start_recording_and_reminders(client, coordinator, caller, week, settings):
    client.force_login(coordinator)
    client.post(reverse("calling:week_hold"), {"on_hold": "1", "note": "No EMS this Sunday"})
    session = EmsSession.objects.get(session_date=services.next_sunday())
    assert session.on_hold and session.hold_note == "No EMS this Sunday"
    dashboard = client.get(reverse("core:coordinator_dashboard")).content.decode()
    assert "No Calling Sewa this week" in dashboard and "Calling Sewa is on after all" in dashboard

    with pytest.raises(services.CallingError, match="no Calling Sewa"):
        services.start_weekly_calling(coordinator)
    caller.email = "caller@example.org"
    caller.save()
    result = send_weekly_reminders()
    assert result["held"] == session and not mail.outbox

    client.force_login(caller)
    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert "No Calling Sewa this week" in page and "No EMS this Sunday" in page


def test_hold_after_calling_started_freezes_results(client, coordinator, caller, week, record):
    session, _, _ = services.start_weekly_calling(coordinator)
    task = session.tasks.get()
    services.set_week_hold(coordinator, True)
    with pytest.raises(services.CallingError):
        record(task, Outcome.YES)
    client.force_login(caller)
    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert "After the call, tap the result" not in page

    services.set_week_hold(coordinator, False)
    record(task, Outcome.YES)
    task.refresh_from_db()
    assert task.latest_outcome == Outcome.YES


def test_only_coordinators_switch_the_hold(client, caller):
    client.force_login(caller)
    assert client.post(reverse("calling:week_hold"), {"on_hold": "1"}).status_code == 403
    assert not EmsSession.objects.exists()
