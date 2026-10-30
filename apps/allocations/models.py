from django.conf import settings
from django.db import models
from django.db.models import F, Q


class CycleStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"


class ChangeType(models.TextChoices):
    INITIAL_IMPORT = "initial_import", "Initial import"
    ASSIGN = "assign", "Assign / move selected"
    MOVE_ALL = "move_all", "Move whole list"
    SWAP = "swap", "Swap lists"
    ROTATE = "rotate", "Rotate lists"
    INDIVIDUAL = "individual", "Individual reassignment"
    STATUS_CHANGE = "status_change", "Contact status change"


class AllocationCycle(models.Model):
    """A rotation period (normally about three months)."""

    name = models.CharField(max_length=100, unique=True)
    start_date = models.DateField()
    planned_end_date = models.DateField()
    status = models.CharField(max_length=10, choices=CycleStatus.choices, default=CycleStatus.PLANNED)
    notes = models.TextField(blank=True, max_length=1000)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(planned_end_date__gte=F("start_date")), name="cycle_end_after_start"
            )
        ]

    def __str__(self):
        return self.name


class AllocationOperation(models.Model):
    """One applied change set: a bulk move, swap, rotation, individual reassignment or import."""

    kind = models.CharField(max_length=20, choices=ChangeType.choices)
    effective_date = models.DateField()
    reason = models.TextField(blank=True, max_length=1000)
    cycle = models.ForeignKey(AllocationCycle, null=True, blank=True, on_delete=models.PROTECT)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    performed_at = models.DateTimeField(auto_now_add=True)
    change_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-performed_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.effective_date} ({self.change_count} contacts)"


class Allocation(models.Model):
    """A caller's responsibility for a contact over ``[effective_from, effective_to)``.

    ``effective_to`` is exclusive (the date the next allocation took effect) and is
    null while the allocation is open. Rows are created once and only ever closed;
    history is the sequence of rows for a contact.
    """

    contact = models.ForeignKey("contacts.Contact", on_delete=models.PROTECT, related_name="allocations")
    caller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="allocations")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    cycle = models.ForeignKey(AllocationCycle, null=True, blank=True, on_delete=models.PROTECT)
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)
    reason = models.TextField(blank=True, max_length=1000)
    operation = models.ForeignKey(
        AllocationOperation, null=True, blank=True, on_delete=models.PROTECT, related_name="opened"
    )
    ended_by_operation = models.ForeignKey(
        AllocationOperation, null=True, blank=True, on_delete=models.PROTECT, related_name="ended"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contact"],
                condition=Q(effective_to__isnull=True),
                name="one_open_allocation_per_contact",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="allocation_dates_ordered",
            ),
            # PostgreSQL additionally has an exclusion constraint preventing overlapping
            # date ranges per contact (migration 0002); it is skipped on SQLite.
        ]
        indexes = [models.Index(fields=["caller", "effective_to"])]

    def __str__(self):
        return f"{self.contact} → {self.caller} from {self.effective_from}"

    @property
    def is_open(self):
        return self.effective_to is None

    @property
    def last_day(self):
        """Inclusive last day, for display."""
        if self.effective_to is None:
            return None
        from datetime import timedelta

        return self.effective_to - timedelta(days=1)
