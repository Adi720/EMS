"""Human-readable presentation of audit events. The stored events are never changed."""

from django.urls import NoReverseMatch, reverse

# action → (description, icon)
ACTIONS = {
    "contact.create": ("Added a Saint", "person-plus"),
    "contact.update": ("Edited a Saint's details", "pencil"),
    "contact.status_change": ("Changed a Saint's status", "toggle-on"),
    "contact.delete": ("Deleted a Saint", "trash"),
    "contact.new_period_ended": ("New Saints became Active (6 months)", "stars"),
    "request.raise": ("Raised a request", "send"),
    "request.approve": ("Approved a request", "check-lg"),
    "request.reject": ("Did not approve a request", "x-lg"),
    "allocation.apply": ("Changed who calls whom", "diagram-3"),
    "allocation.cycle_create": ("Started an allocation cycle", "calendar-plus"),
    "task.moved": ("Moved a call to another caller", "arrow-left-right"),
    "task.reinstated": ("Put a call back on a list", "arrow-counterclockwise"),
    "task.withdrawn": ("Withdrew a call", "dash-circle"),
    "call.attempt": ("Recorded a call result", "telephone"),
    "session.create": ("Created a congregation", "calendar-plus"),
    "session.update": ("Edited a congregation", "pencil"),
    "session.open": ("Started calling", "play-fill"),
    "session.reopen": ("Reopened calling", "unlock"),
    "session.close": ("Closed calling", "lock"),
    "session.refresh": ("Refreshed the call lists", "arrow-clockwise"),
    "import.upload": ("Uploaded a workbook", "cloud-arrow-up"),
    "import.mapping": ("Checked the import columns", "layout-three-columns"),
    "import.caller_mapping": ("Matched a workbook caller", "headset"),
    "import.row_update": ("Fixed an import row", "wrench"),
    "import.create_callers": ("Created caller logins from the workbook", "person-plus"),
    "import.commit": ("Imported Saints", "cloud-arrow-down"),
    "import.cancel": ("Cancelled an import", "x-circle"),
    "team.create": ("Added a caller", "person-plus"),
    "team.update": ("Edited a caller", "pencil"),
    "team.password_reset": ("Reset a caller's password", "key"),
    "team.deactivate": ("Deactivated a caller", "person-x"),
    "team.activate": ("Reactivated a caller", "person-check"),
    "team.stall_lead_create": ("Created the Stall Lead login", "shop"),
    "team.leave_start": ("Marked a caller On Leave", "cup-hot"),
    "session.hold": ("No Calling Sewa this week", "pause-circle"),
    "session.resume": ("Calling Sewa back on", "play-circle"),
    "team.leave_end": ("Caller back from leave", "arrow-return-left"),
    "export.contacts": ("Exported the Saints list", "download"),
    "export.session_summary": ("Exported a congregation summary", "download"),
    "export.session_tasks": ("Exported a call list", "download"),
    "export.monthly": ("Exported a monthly report", "download"),
    "export.import_rows": ("Exported an import row report", "download"),
    "reminder.email": ("Sent a reminder email", "envelope"),
}

# Activity type (for filtering) → action prefixes
CATEGORIES = {
    "saints": ("Saints", ["contact."]),
    "assignments": ("Assignments", ["allocation."]),
    "calling": ("Calling", ["session.", "call.", "task."]),
    "team": ("Calling Team", ["team."]),
    "import": ("Import", ["import."]),
    "exports": ("Exports", ["export."]),
    "reminders": ("Reminders", ["reminder."]),
    "requests": ("Requests", ["request."]),
}

RECORD_URLS = {
    "contacts.contact": "contacts:detail",
    "calling.emssession": "calling:session_detail",
    "calling.calltask": "calling:task_detail",
    "imports.importbatch": "imports:detail",
    "allocations.allocationoperation": "allocations:operation",
}


def describe(event):
    """Attach .label, .icon and .record_url to an AuditEvent for display."""
    label, icon = ACTIONS.get(
        event.action, (event.action.replace(".", " ").replace("_", " ").capitalize(), "dot")
    )
    event.label, event.icon, event.record_url = label, icon, None
    name = RECORD_URLS.get(event.object_type)
    if event.object_type == "accounts.user" and event.action.startswith("team."):
        name = "team:detail"
    if event.action.endswith(".delete"):
        name = None  # the record no longer exists
    if name and event.object_id.isdigit():
        try:
            event.record_url = reverse(name, args=[int(event.object_id)])
        except NoReverseMatch:
            event.record_url = None
    return event
