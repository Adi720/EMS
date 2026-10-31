"""Caller performance and Calling Team status.

Performance = calls attempted ÷ calls assigned (withdrawn calls not counted) for the
congregations of the last N months that have already taken place. A caller below
PARTIALLY_ACTIVE_BELOW % is shown as Partially Active — automatically, never stored.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.dates import add_months


class TeamStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PARTIALLY_ACTIVE = "partially_active", "Partially Active"
    ON_LEAVE = "on_leave", "On Leave"
    INACTIVE = "inactive", "Inactive"


def window(months=None, today=None):
    """(first day, today): congregations on or after the first day and before today count."""
    today = today or timezone.localdate()
    return add_months(today, -(months or settings.PERFORMANCE_MONTHS)), today


def performance(months=None, today=None, callers=None):
    """{caller id: metrics row with completion_rate} for the window."""
    from apps.calling.models import CallTask
    from apps.reports import metrics

    start, today = window(months, today)
    tasks = CallTask.objects.filter(session__session_date__gte=start, session__session_date__lt=today)
    if callers is not None:
        tasks = tasks.filter(caller__in=callers)
    return {row["caller"]: row for row in metrics.grouped(tasks, "caller")}


def team_status(user, row=None):
    if not user.is_active:
        return TeamStatus.INACTIVE
    if user.is_on_leave:
        return TeamStatus.ON_LEAVE
    rate = row["completion_rate"] if row else None
    if rate is not None and rate < settings.PARTIALLY_ACTIVE_BELOW:
        return TeamStatus.PARTIALLY_ACTIVE
    return TeamStatus.ACTIVE


def status_for(user, today=None):
    return team_status(user, performance(today=today, callers=[user]).get(user.pk))
