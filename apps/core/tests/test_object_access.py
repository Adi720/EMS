"""Object-level access: callers and role-less users cannot reach coordinator records by ID."""

import pytest
from django.urls import reverse

from apps.allocations.models import AllocationOperation
from apps.audit.models import AuditEvent
from apps.calling.models import CallAttempt
from apps.contacts.models import ContactStatusChange
from apps.imports.models import ImportBatch


@pytest.fixture
def objects(make_contact, caller2, allocate, make_session, coordinator):
    contact = make_contact()
    operation = allocate(contact, caller2)
    session = make_session()
    batch = ImportBatch.objects.create(
        uploaded_by=coordinator,
        original_filename="x.csv",
        file_sha256="0" * 64,
        file_type="csv",
        contact_sheet="CSV",
    )
    row = batch.rows.create(row_number=2, raw_values={})
    return {
        "contact": contact,
        "operation": operation,
        "session": session,
        "batch": batch,
        "row": row,
        "task": session.tasks.get(),
    }


def coordinator_urls(o):
    return [
        reverse("contacts:detail", args=[o["contact"].pk]),
        reverse("contacts:edit", args=[o["contact"].pk]),
        reverse("contacts:status", args=[o["contact"].pk]),
        reverse("contacts:reassign", args=[o["contact"].pk]),
        reverse("allocations:operation", args=[o["operation"].pk]),
        reverse("calling:session_detail", args=[o["session"].pk]),
        reverse("calling:session_edit", args=[o["session"].pk]),
        reverse("calling:session_action", args=[o["session"].pk, "close"]),
        reverse("reports:session_export", args=[o["session"].pk]),
        reverse("imports:detail", args=[o["batch"].pk]),
        reverse("imports:mapping", args=[o["batch"].pk]),
        reverse("imports:caller_mapping", args=[o["batch"].pk]),
        reverse("imports:row_edit", args=[o["batch"].pk, o["row"].pk]),
        reverse("imports:commit", args=[o["batch"].pk]),
        reverse("imports:cancel", args=[o["batch"].pk]),
        reverse("imports:row_report", args=[o["batch"].pk]),
    ]


@pytest.mark.parametrize("fixture", ["caller", "no_role_user"])
def test_non_coordinators_cannot_read_or_write_coordinator_records(client, request, objects, fixture):
    before = (
        ContactStatusChange.objects.count(),
        AllocationOperation.objects.count(),
        AuditEvent.objects.count(),
    )
    client.force_login(request.getfixturevalue(fixture))
    for url in coordinator_urls(objects):
        assert client.get(url).status_code == 403, url
        assert client.post(url, {"new_status": "inactive", "outcome": "yes"}).status_code == 403, url
    after = (
        ContactStatusChange.objects.count(),
        AllocationOperation.objects.count(),
        AuditEvent.objects.count(),
    )
    assert before == after
    objects["session"].refresh_from_db()
    assert objects["session"].is_open


@pytest.mark.parametrize("fixture", ["caller", "no_role_user"])
def test_other_callers_task_is_not_found(client, request, objects, fixture):
    client.force_login(request.getfixturevalue(fixture))
    task = objects["task"]  # belongs to caller2
    assert client.get(reverse("calling:task_detail", args=[task.pk])).status_code in {403, 404}
    assert client.post(reverse("calling:quick_attempt", args=[task.pk]), {"outcome": "yes"}).status_code in {
        403,
        404,
    }
    assert not CallAttempt.objects.exists()


def test_anonymous_is_redirected_from_object_urls(client, objects):
    for url in coordinator_urls(objects) + [reverse("calling:task_detail", args=[objects["task"].pk])]:
        response = client.get(url)
        assert response.status_code == 302 and response.url.startswith(reverse("accounts:login")), url
