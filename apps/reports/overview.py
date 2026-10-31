"""Coordinator dashboard overview: real counts, dashboard state and the setup checklist.

States
------
setup      no callers, no active Saints, or no Saint has a caller yet
ready      Saints are allocated; calling for the coming Sunday has not started
calling    calling is open for the coming Sunday
completed  calling for the coming Sunday has been closed
"""

from django.urls import reverse

from apps.allocations.services import allocated_contact_ids, callers_queryset
from apps.calling.models import SessionStatus
from apps.contacts.models import CALLABLE_STATUSES, Contact
from apps.imports.models import BatchStatus, ImportBatch


def build_overview(user, week_session):
    active_saints = Contact.objects.filter(status__in=CALLABLE_STATUSES).count()
    caller_count = callers_queryset().count()
    allocated = Contact.objects.filter(status__in=CALLABLE_STATUSES, pk__in=allocated_contact_ids()).count()
    unallocated = active_saints - allocated
    staged_import = ImportBatch.objects.filter(status=BatchStatus.STAGED).order_by("-uploaded_at").first()

    if caller_count == 0 or active_saints == 0 or allocated == 0:
        state = "setup"
    elif week_session is None or week_session.status == SessionStatus.DRAFT:
        state = "ready"
    elif week_session.is_open:
        state = "calling"
    else:
        state = "completed"

    steps = _steps(user, caller_count, active_saints, unallocated, staged_import, week_session)
    remaining = [step for step in steps if not step["done"]]
    if remaining:
        remaining[0]["next"] = True
    return {
        "state": state,
        "active_saints": active_saints,
        "caller_count": caller_count,
        "allocated": allocated,
        "unallocated": unallocated,
        "staged_import": staged_import,
        "steps_remaining": remaining,
        "steps_done": len(steps) - len(remaining),
        "steps_total": len(steps),
        "next_step": remaining[0] if remaining else None,
    }


def _steps(user, caller_count, active_saints, unallocated, staged_import, week_session):
    if staged_import:
        saints_action = (
            reverse("imports:detail", args=[staged_import.pk]),
            f"Continue import #{staged_import.pk}",
        )
        saints_text = (
            f"“{staged_import.original_filename}” is uploaded but not imported yet. "
            "Review the rows and confirm to bring the Saints in."
        )
    else:
        saints_action = (reverse("imports:upload"), "Import Excel workbook")
        saints_text = "Import the EMS workbook, or add Saints one by one."
    callers_action = (reverse("team:create"), "Add a caller")
    calling_started = week_session is not None and week_session.status != SessionStatus.DRAFT
    return [
        {
            "key": "callers",
            "title": "Create caller accounts",
            "text": (
                f"{caller_count} caller(s) so far. Each caller needs an account with the Caller role."
                if caller_count
                else "Each person who makes calls needs their own login with the Caller role."
            ),
            "done": caller_count > 0,
            "url": callers_action[0],
            "action": callers_action[1],
        },
        {
            "key": "saints",
            "title": "Bring in the Saints",
            "text": saints_text,
            "done": active_saints > 0,
            "url": saints_action[0],
            "action": saints_action[1],
            "secondary_url": reverse("contacts:create"),
            "secondary_action": "Add a Saint",
        },
        {
            "key": "assignments",
            "title": "Give every Saint a caller",
            "text": (
                f"{unallocated} active Saint(s) have no caller and would not be called."
                if active_saints and unallocated
                else "Each Saint is looked after by one caller for about three months."
            ),
            "done": active_saints > 0 and unallocated == 0,
            "url": reverse("allocations:change") + "?caller=none&kind=assign",
            "action": "Assign Saints",
        },
        {
            "key": "calling",
            "title": "Start calling",
            "text": "One click builds every caller's list for the coming Sunday.",
            "done": calling_started,
            "url": None,
            "action": "",
        },
    ]
