"""The Charts page: ring (pie) charts, week trends and per-caller bars."""

from datetime import date

import pytest
from django.urls import reverse

from apps.calling.models import Outcome
from apps.reports import charts

pytestmark = pytest.mark.django_db


def test_ring_slices_add_up_and_leave_gaps():
    ring = charts.ring([("yes", "Yes", 3), ("not_possible", "Not Possible", 1), ("unknown", "Unknown", 0)])
    assert ring["total"] == 4
    yes, no, unknown = ring["segments"]
    assert (yes["pct"], no["pct"], unknown["pct"]) == (75, 25, 0)
    assert yes["dash"].startswith("73.80") and yes["offset"] == "-0.00"
    assert no["offset"] == "-75.00"
    assert "dash" not in unknown  # nothing drawn for an empty slice
    whole = charts.ring([("yes", "Yes", 5)])["segments"][0]
    assert whole["dash"].startswith("100.00")  # a single slice is a full ring, no gap


def test_nice_axis_maximum():
    assert [charts.nice_max(v) for v in (0, 3, 7, 12, 26, 51, 130)] == [5, 5, 10, 20, 50, 100, 200]


def test_caller_bars_are_best_first():
    rows = [
        {
            "caller_obj": "Low",
            "assigned": 4,
            "completed": 1,
            "completion_rate": 25,
            "yes": 1,
            "not_possible": 0,
            "will_try": 0,
            "unknown": 3,
            "not_attempted": 2,
        },
        {
            "caller_obj": "High",
            "assigned": 2,
            "completed": 2,
            "completion_rate": 100,
            "yes": 1,
            "not_possible": 1,
            "will_try": 0,
            "unknown": 0,
            "not_attempted": 0,
        },
    ]
    bars = charts.caller_bars(rows)
    assert [b["caller"] for b in bars] == ["High", "Low"]
    assert [p["key"] for p in bars[0]["parts"]] == ["yes", "not_possible"]
    low = {p["key"]: p["value"] for p in bars[1]["parts"]}
    assert low == {"yes": 1, "not_connected": 1, "not_called": 2}  # Unknown 3 = 1 tried + 2 not called
    assert bars[1]["parts"][2]["width"] == 50


@pytest.fixture
def results(make_contact, allocate, make_session, caller, caller2, record):
    for i, who in enumerate([caller, caller, caller2]):
        allocate(make_contact(full_name=f"Chart Saint {i}"), who)
    sessions = [make_session(session_date=date(2026, 10, 18)), make_session(session_date=date(2026, 10, 25))]
    for session in sessions:
        tasks = list(session.tasks.order_by("contact__full_name"))
        record(tasks[0], Outcome.YES)
        record(tasks[1], Outcome.NOT_POSSIBLE)
    return sessions


@pytest.mark.parametrize("period", ["week", "month", "3m"])
def test_charts_page_for_each_period(client, coordinator, results, period):
    client.force_login(coordinator)
    params = {"period": period, "month": "2026-10"}
    if period == "week":
        params["week"] = "2026-10-25"
    page = client.get(reverse("reports:charts"), params)
    assert page.status_code == 200
    content = page.content.decode()
    assert "Results of the calls" in content and "Saints by status" in content
    assert "Results by caller" in content and 'class="ems-ring__seg ems-c-yes"' in content
    assert ("Calls made each week" in content) == (period != "week")  # one week has no trend
    assert "By area" not in content


def test_ring_numbers_match_the_report(client, coordinator, results):
    client.force_login(coordinator)
    context = client.get(reverse("reports:charts"), {"period": "month", "month": "2026-10"}).context
    by_key = {s["key"]: s["value"] for s in context["results_ring"]["segments"]}
    summary = context["summary"]
    assert by_key == {
        "yes": summary["yes"],
        "not_possible": summary["not_possible"],
        "will_try": summary["will_try"],
        "not_connected": summary["unknown"] - summary["not_attempted"],
        "not_called": summary["not_attempted"],
    }
    assert by_key["not_connected"] == 0 and by_key["not_called"] == 2
    assert context["results_ring"]["total"] == summary["assigned"] == 6


def test_charts_and_reports_link_to_each_other_and_menu(client, coordinator):
    client.force_login(coordinator)
    charts_page = client.get(reverse("reports:charts"), {"period": "3m"}).content.decode()
    assert f"{reverse('reports:monthly')}?period=3m" in charts_page
    reports_page = client.get(reverse("reports:monthly"), {"period": "3m"}).content.decode()
    assert f"{reverse('reports:charts')}?period=3m" in reports_page
    assert ">Charts</span>" in reports_page


def test_empty_period_shows_a_message(client, coordinator):
    client.force_login(coordinator)
    content = client.get(reverse("reports:charts"), {"period": "month", "month": "2025-01"}).content.decode()
    assert "No calls in this period" in content


@pytest.mark.parametrize("fixture", ["caller", "no_role_user"])
def test_charts_are_coordinator_only(client, request, fixture):
    client.force_login(request.getfixturevalue(fixture))
    assert client.get(reverse("reports:charts")).status_code == 403
