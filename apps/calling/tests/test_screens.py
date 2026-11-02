"""Phase 3 screens: My calls states and the EMS Congregations page."""

from django.urls import reverse

from apps.calling.models import Outcome
from apps.calling.services import start_weekly_calling


def test_my_calls_before_calling_starts_explains_why(client, caller, make_contact, allocate):
    for _ in range(2):
        allocate(make_contact(), caller)
    client.force_login(caller)
    response = client.get(reverse("core:caller_dashboard"))
    content = response.content.decode()
    assert response.context["assigned_saints"] == 2
    assert "{%" not in content and "{{" not in content
    assert "No calls to make yet" in content and "2 Saints" in content
    assert response.context["week_label"] in content


def test_my_calls_marks_current_result_and_all_done(
    client, caller, coordinator, make_contact, allocate, record
):
    allocate(make_contact(full_name="Only Saint"), caller)
    session, _, _ = start_weekly_calling(coordinator)
    task = session.tasks.get()
    client.force_login(caller)
    content = client.get(reverse("core:caller_dashboard")).content.decode()
    assert 'name="notes"' in content and ">Remarks</label>" in content
    assert "{%" not in content and "{{" not in content
    assert content.index('class="ems-outcomes mt-2"') < content.index('id="notes-')
    assert 'class="ems-request-link ems-muted mt-2"' in content
    assert "After the call, tap a result" not in content and "Set call-back time" not in content
    assert "All calls done" not in content
    record(task, Outcome.WILL_TRY)
    content = client.get(reverse("core:caller_dashboard")).content.decode()
    assert "All calls done" in content
    assert 'ems-outcome--will_try is-current" aria-pressed="true"' in content
    assert "Update the result" not in content


def test_my_calls_session_switcher_renders(client, caller, make_contact, allocate, make_session):
    allocate(make_contact(), caller)
    first = make_session()
    make_session(session_date=first.session_date.replace(day=8))
    client.force_login(caller)

    content = client.get(reverse("core:caller_dashboard")).content.decode()

    assert 'name="session"' in content
    assert "Show congregation" in content


def test_congregations_page_states(client, coordinator, caller, make_contact, allocate):
    allocate(make_contact(), caller)
    client.force_login(coordinator)
    content = client.get(reverse("calling:session_list")).content.decode()
    assert reverse("calling:start_week") in content and "No congregations yet" in content

    client.post(reverse("calling:start_week"))
    response = client.get(reverse("calling:session_list"))
    content = response.content.decode()
    session = response.context["week_session"]
    assert response.context["week_summary"]["assigned"] == 1
    assert "View calling progress" in content
    assert reverse("calling:session_action", args=[session.pk, "close"]) in content
