"""Every page renders (200) with realistic synthetic data for its intended role."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.calling.models import Outcome
from apps.contacts.models import ContactStatus, StatusReason
from apps.contacts.services import change_status
from apps.imports import services as import_services
from apps.imports.synthetic import build_workbook


@pytest.fixture
def data(make_contact, caller, caller2, allocate, make_session, record, coordinator):
    contacts = [make_contact(area=area) for area in ["North", "South", "North"]]
    operation = allocate(contacts[0], caller)
    allocate(contacts[1], caller2)
    allocate(contacts[2], caller)
    session = make_session()
    task = session.tasks.get(contact=contacts[0])
    record(task, Outcome.YES, notes="See you Sunday", callback_at=None)
    change_status(
        contacts[1],
        ContactStatus.ON_HOLD,
        coordinator,
        reason_category=StatusReason.TEMPORARILY_AWAY,
        review_date=date(2026, 10, 1),
    )
    batch = import_services.stage_upload(
        SimpleUploadedFile("synthetic.xlsx", build_workbook(30)[0]), coordinator
    )
    return {"contact": contacts[0], "operation": operation, "session": session, "task": task, "batch": batch}


def test_coordinator_pages_render(client, coordinator, data):
    client.force_login(coordinator)
    batch = data["batch"]
    urls = [
        reverse("core:coordinator_dashboard"),
        reverse("contacts:list"),
        reverse("contacts:create"),
        reverse("contacts:detail", args=[data["contact"].pk]),
        reverse("contacts:edit", args=[data["contact"].pk]),
        reverse("allocations:home"),
        reverse("allocations:change"),
        reverse("allocations:change") + "?caller=none&kind=assign",
        reverse("allocations:cycle_create"),
        reverse("allocations:operation", args=[data["operation"].pk]),
        reverse("calling:session_list"),
        reverse("calling:session_create"),
        reverse("calling:session_detail", args=[data["session"].pk]),
        reverse("calling:session_detail", args=[data["session"].pk]) + "?show=unknown",
        reverse("calling:session_edit", args=[data["session"].pk]),
        reverse("calling:task_detail", args=[data["task"].pk]),
        reverse("reports:monthly") + "?month=2026-11",
        reverse("audit:event_list"),
        reverse("imports:list"),
        reverse("imports:upload"),
        reverse("team:list"),
        reverse("team:create"),
        reverse("team:detail", args=[data["task"].caller_id]),
        reverse("team:edit", args=[data["task"].caller_id]),
        reverse("team:password", args=[data["task"].caller_id]),
        reverse("contacts:list") + "?status=active&q=Synthetic",
        reverse("contacts:list") + "?q=no-such-saint",
        reverse("allocations:change") + "?kind=move_all&from_caller=" + str(data["task"].caller_id),
        reverse("imports:mapping", args=[batch.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 200, url

    client.post(reverse("imports:mapping", args=[batch.pk]), batch.column_mapping)
    for url in [
        reverse("imports:detail", args=[batch.pk]),
        reverse("imports:detail", args=[batch.pk]) + "?status=needs_resolution",
        reverse("imports:row_edit", args=[batch.pk, batch.rows.first().pk]),
    ]:
        assert client.get(url).status_code == 200, url
    preview = client.post(
        reverse("allocations:change"),
        {
            "kind": "rotate",
            "rotation_callers": [
                data["task"].caller_id,
                data["session"].tasks.exclude(caller=data["task"].caller).first().caller_id,
            ],
            "effective_date": "2026-11-02",
            "reason": "Rotation",
            "action": "preview",
        },
    )
    assert preview.status_code == 200 and preview.context["changes"]


def test_caller_pages_render(client, caller, data):
    client.force_login(caller)
    assert client.get(reverse("core:caller_dashboard")).status_code == 200
    assert client.get(reverse("core:caller_dashboard") + "?show=completed").status_code == 200
    assert client.get(reverse("calling:task_detail", args=[data["task"].pk])).status_code == 200
    assert client.get(reverse("accounts:password_change")).status_code == 200
