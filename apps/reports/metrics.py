"""Calling metrics (requirements §8). All counts are over non-withdrawn tasks.

Assigned      = non-withdrawn tasks
Completed     = tasks with ≥1 attempt (any outcome)
Not attempted = Assigned − Completed
Connected     = latest outcome ∈ {Yes, Not Possible, Will Try}
Yes / Not Possible / Will Try = latest outcome
Unknown       = no attempt, or latest outcome Call Not Connected

Yes + Not Possible + Will Try + Unknown = Assigned (each task counted once).
"""

from django.db.models import Count, Q

from apps.calling.models import CONNECTED_OUTCOMES, CallTask, Outcome, TaskStatus

METRIC_FIELDS = [
    "assigned",
    "completed",
    "not_attempted",
    "connected",
    "yes",
    "not_possible",
    "will_try",
    "unknown",
]

METRIC_LABELS = {
    "assigned": "Assigned",
    "completed": "Completed (attempted)",
    "not_attempted": "Not yet attempted",
    "connected": "Connected",
    "yes": "Yes",
    "not_possible": "Not Possible",
    "will_try": "Will Try",
    "unknown": "Unknown",
}

_AGGREGATES = {
    "assigned": Count("id"),
    "completed": Count("id", filter=Q(attempt_count__gt=0)),
    "not_attempted": Count("id", filter=Q(attempt_count=0)),
    "connected": Count("id", filter=Q(latest_outcome__in=CONNECTED_OUTCOMES)),
    "yes": Count("id", filter=Q(latest_outcome=Outcome.YES)),
    "not_possible": Count("id", filter=Q(latest_outcome=Outcome.NOT_POSSIBLE)),
    "will_try": Count("id", filter=Q(latest_outcome=Outcome.WILL_TRY)),
    "unknown": Count("id", filter=Q(attempt_count=0) | Q(latest_outcome=Outcome.NOT_CONNECTED)),
}


def assigned_tasks(qs=None):
    qs = CallTask.objects.all() if qs is None else qs
    return qs.filter(status=TaskStatus.OPEN)


def _finish(row):
    row = {**row}
    for field in METRIC_FIELDS:
        row[field] = row.get(field) or 0
    assigned = row["assigned"]
    row["completion_rate"] = round(100 * row["completed"] / assigned) if assigned else None
    row["connection_rate"] = round(100 * row["connected"] / row["completed"]) if row["completed"] else None
    row["reconciles"] = row["yes"] + row["not_possible"] + row["will_try"] + row["unknown"] == assigned
    return row


def summarize(qs=None):
    return _finish(assigned_tasks(qs).aggregate(**_AGGREGATES))


def grouped(qs, *fields):
    rows = assigned_tasks(qs).order_by().values(*fields).annotate(**_AGGREGATES).order_by(*fields)
    return [_finish(row) for row in rows]


def by_caller(qs=None):
    from apps.accounts.models import User

    rows = grouped(qs, "caller")
    users = User.objects.in_bulk([r["caller"] for r in rows])
    for row in rows:
        row["caller_obj"] = users.get(row["caller"])
    return sorted(rows, key=lambda r: str(r["caller_obj"]).lower())


def by_session(qs=None):
    from apps.calling.models import EmsSession

    rows = grouped(qs, "session")
    sessions = EmsSession.objects.in_bulk([r["session"] for r in rows])
    for row in rows:
        row["session_obj"] = sessions.get(row["session"])
    return sorted(rows, key=lambda r: r["session_obj"].session_date, reverse=True)


def by_area(qs=None):
    rows = grouped(qs, "contact__area")
    return sorted(rows, key=lambda r: (r["contact__area"] or "").lower())


def unique_contacts(qs, outcome):
    return assigned_tasks(qs).filter(latest_outcome=outcome).values("contact").distinct().count()
