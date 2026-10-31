from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.contacts.models import AppendOnlyModel


class SessionStatus(models.TextChoices):
    DRAFT = "draft", "Not started"
    OPEN = "open", "Calling open"
    CLOSED = "closed", "Calling closed"


def congregation_label(day):
    """Display name used everywhere, e.g. 'EMS Congregation (1 Nov 2026)'."""
    return f"EMS Congregation ({day.day} {day:%b %Y})"


class Outcome(models.TextChoices):
    YES = "yes", "Yes"
    NOT_POSSIBLE = "not_possible", "Not Possible"
    WILL_TRY = "will_try", "Will Try"
    NOT_CONNECTED = "not_connected", "Call Not Connected"


CONNECTED_OUTCOMES = frozenset({Outcome.YES, Outcome.NOT_POSSIBLE, Outcome.WILL_TRY})

OUTCOME_HELP = {
    Outcome.YES: "Intends to attend",
    Outcome.NOT_POSSIBLE: "Cannot attend",
    Outcome.WILL_TRY: "Unsure — not a confirmation",
    Outcome.NOT_CONNECTED: "Attempted, did not connect",
}


class TaskStatus(models.TextChoices):
    OPEN = "open", "Open"
    WITHDRAWN = "withdrawn", "Withdrawn"


class ReportCategory(models.TextChoices):
    """Exactly one per assigned task: Yes + Not possible + Will try + Unknown = Assigned."""

    YES = "yes", "Yes"
    NOT_POSSIBLE = "not_possible", "Not Possible"
    WILL_TRY = "will_try", "Will Try"
    UNKNOWN = "unknown", "Unknown"


class EmsSession(models.Model):
    """One Sunday EMS Congregation (shown to users as 'EMS Congregation (1 Nov 2026)')."""

    session_date = models.DateField("Sunday date")
    title = models.CharField(max_length=120, blank=True)
    venue = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, max_length=1000)
    status = models.CharField(max_length=10, choices=SessionStatus.choices, default=SessionStatus.DRAFT)
    # "No Calling Sewa this week": calling cannot start, nothing can be recorded, no reminders.
    on_hold = models.BooleanField("No calling this week", default=False)
    hold_note = models.CharField(max_length=200, blank=True)
    # Empty when created automatically by the Saturday reminder job.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-session_date", "venue"]
        verbose_name = "EMS congregation"
        constraints = [
            models.UniqueConstraint(fields=["session_date", "venue"], name="one_session_per_date_venue")
        ]

    def __str__(self):
        label = self.label
        if self.title:
            label += f" — {self.title}"
        if self.venue:
            label += f" ({self.venue})"
        return label

    @property
    def label(self):
        return congregation_label(self.session_date)

    @property
    def is_open(self):
        return self.status == SessionStatus.OPEN


class CallTask(models.Model):
    """One contact to call for one session, with the caller responsible for that session."""

    session = models.ForeignKey(EmsSession, on_delete=models.PROTECT, related_name="tasks")
    contact = models.ForeignKey("contacts.Contact", on_delete=models.PROTECT, related_name="call_tasks")
    caller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="call_tasks")
    allocation = models.ForeignKey(
        "allocations.Allocation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=10, choices=TaskStatus.choices, default=TaskStatus.OPEN)
    withdrawn_reason = models.CharField(max_length=200, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    latest_outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    callback_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["contact__full_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["session", "contact"], name="one_task_per_contact_per_session"),
            models.CheckConstraint(
                condition=Q(status=TaskStatus.OPEN) | Q(attempt_count=0),
                name="attempted_tasks_never_withdrawn",
            ),
            models.CheckConstraint(
                condition=(Q(attempt_count=0) & Q(latest_outcome=""))
                | (Q(attempt_count__gt=0) & ~Q(latest_outcome="")),
                name="latest_outcome_matches_attempts",
            ),
        ]
        indexes = [models.Index(fields=["session", "caller", "status"])]

    def __str__(self):
        return f"{self.contact} — {self.session}"

    @property
    def is_completed(self):
        return self.attempt_count > 0

    @property
    def report_category(self):
        if self.attempt_count == 0 or self.latest_outcome == Outcome.NOT_CONNECTED:
            return ReportCategory.UNKNOWN
        return ReportCategory(self.latest_outcome)

    @property
    def is_connected(self):
        return self.latest_outcome in CONNECTED_OUTCOMES


class CallAttempt(AppendOnlyModel):
    task = models.ForeignKey(CallTask, on_delete=models.PROTECT, related_name="attempts")
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    notes = models.TextField(blank=True, max_length=1000)
    callback_at = models.DateTimeField("Call back at", null=True, blank=True)
    attempted_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-attempted_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(outcome__in=Outcome.values), name="attempt_outcome_valid")
        ]

    def __str__(self):
        return f"{self.task}: {self.get_outcome_display()}"
