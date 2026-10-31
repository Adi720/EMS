"""My Report, the daily Sewa blessing and the Weekly / Monthly / 3 Months report buttons."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.calling.models import Outcome

pytestmark = pytest.mark.django_db
BLESSING = "Please do Simran before starting the Sewa."


@pytest.fixture
def last_week(make_contact, allocate, make_session, caller, record):
    saints = [make_contact(full_name=f"Report Saint {i}") for i in range(4)]
    for saint in saints:
        allocate(saint, caller)
    sunday = timezone.localdate() - timedelta(days=(timezone.localdate().weekday() + 1) % 7 or 7)
    session = make_session(session_date=sunday)
    tasks = list(session.tasks.order_by("contact__full_name"))
    record(tasks[0], Outcome.YES)
    record(tasks[1], Outcome.WILL_TRY)
    record(tasks[2], Outcome.NOT_CONNECTED)
    return session


def test_my_report_shows_own_figures_chart_and_table(client, caller, caller2, last_week):
    client.force_login(caller)
    page = client.get(reverse("core:my_report")).content.decode()
    assert "Calls made, % of calls given" in page
    assert 'data-tip="' in page and "3 of 4 calls (75%)" in page
    assert f"{last_week.session_date.day} {last_week.session_date:%b %Y}" in page  # table row
    client.force_login(caller2)
    page = client.get(reverse("core:my_report")).content.decode()
    assert "No calls in this period yet" in page  # never someone else's calls


def test_blessing_shows_once_a_day(client, caller):
    client.force_login(caller)
    assert BLESSING in client.get(reverse("core:caller_dashboard")).content.decode()
    response = client.post(reverse("accounts:blessing_seen"), {"next": reverse("core:my_report")})
    assert response.status_code == 302 and response.url == reverse("core:my_report")
    assert BLESSING not in client.get(reverse("core:caller_dashboard")).content.decode()
    caller.refresh_from_db()
    caller.blessing_shown_on = timezone.localdate() - timedelta(days=1)
    caller.save()
    assert BLESSING in client.get(reverse("core:caller_dashboard")).content.decode()


def test_blessing_next_cannot_leave_the_site(client, caller):
    client.force_login(caller)
    response = client.post(reverse("accounts:blessing_seen"), {"next": "https://evil.example/"})
    assert response.url == reverse("core:home")


def test_caller_tab_bar(client, caller, coordinator):
    client.force_login(caller)
    page = client.get(reverse("core:caller_dashboard")).content.decode()
    assert 'class="ems-tabbar' in page and "Raise Request" in page and "My Report" in page
    client.force_login(coordinator)
    assert 'class="ems-tabbar' not in client.get(reverse("core:coordinator_dashboard")).content.decode()


@pytest.mark.parametrize("period", ["week", "month", "3m"])
def test_report_periods(client, coordinator, last_week, period):
    client.force_login(coordinator)
    params = {"period": period}
    if period == "month":
        params["month"] = f"{last_week.session_date:%Y-%m}"
    page = client.get(reverse("reports:monthly"), params)
    assert page.status_code == 200
    assert page.context["summary"]["assigned"] == 4 and page.context["summary"]["completed"] == 3
    assert "Weekly" in page.content.decode() and "3 Months" in page.content.decode()
    export = client.get(reverse("reports:monthly_export"), {**params, "format": "csv"})
    assert export.status_code == 200 and "TOTAL,4,3" in export.content.decode("utf-8-sig")
