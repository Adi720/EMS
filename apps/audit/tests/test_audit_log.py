"""Audit log presentation: readable labels, filters and record links."""

import re
from datetime import timedelta
from pathlib import Path

from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.presentation import ACTIONS, describe

APPS = Path(__file__).resolve().parents[2]


def test_every_recorded_action_has_a_readable_label():
    used = set()
    for source in APPS.rglob("*.py"):
        if "tests" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        used |= set(re.findall(r'log_event\(\s*[^,]+,\s*"([a-z_]+\.[a-z_]+)"', text))
        # Actions built with f-strings:
        if 'f"task.{result}"' in text:
            used |= {"task.moved", "task.reinstated"}
        if 'f"export.session_{kind}"' in text:
            used |= {"export.session_summary", "export.session_tasks"}
    assert used, "no log_event calls found"
    assert used <= set(ACTIONS), sorted(used - set(ACTIONS))


def test_filters_labels_and_links(client, coordinator, make_contact):
    contact = make_contact()  # records "contact.create"
    old = AuditEvent.objects.create(actor=coordinator, action="export.monthly", summary="Exported")
    AuditEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=10))
    client.force_login(coordinator)

    response = client.get(reverse("audit:event_list"), {"type": "saints"})
    events = list(response.context["object_list"])
    assert [e.action for e in events] == ["contact.create"]
    assert events[0].label == "Added a Saint"
    assert events[0].record_url == reverse("contacts:detail", args=[contact.pk])
    assert "Added a Saint" in response.content.decode()

    since = (timezone.localdate() - timedelta(days=2)).isoformat()
    actions = {
        e.action for e in client.get(reverse("audit:event_list"), {"from": since}).context["object_list"]
    }
    assert "export.monthly" not in actions and "contact.create" in actions

    system = client.get(reverse("audit:event_list"), {"person": "system"}).context["object_list"]
    assert all(e.actor_id is None for e in system)


def test_unknown_action_still_readable():
    event = describe(AuditEvent(action="something.new_thing", summary="x", object_type="", object_id=""))
    assert event.label == "Something new thing" and event.record_url is None
