from django.conf import settings
from django.db import models


class BatchStatus(models.TextChoices):
    STAGED = "staged", "Staged (not imported)"
    COMMITTED = "committed", "Imported"
    CANCELLED = "cancelled", "Cancelled"


class RowStatus(models.TextChoices):
    READY = "ready", "Ready"
    WARNING = "warning", "Warning"
    NEEDS_RESOLUTION = "needs_resolution", "Needs resolution"
    ALREADY_IMPORTED = "already_imported", "Already imported"
    SKIPPED = "skipped", "Skipped"


class RowAction(models.TextChoices):
    AUTO = "", "Automatic"
    CREATE = "create", "Create as a new contact"
    LINK = "link", "Link to an existing contact"
    SKIP = "skip", "Skip this row"


class RowOutcome(models.TextChoices):
    CREATED = "created", "Created"
    LINKED = "linked", "Linked to existing"
    SKIPPED = "skipped", "Skipped"


class ImportBatch(models.Model):
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    original_filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64, db_index=True)
    file_type = models.CharField(max_length=10)
    sheet_names = models.JSONField(default=list)
    contact_sheet = models.CharField(max_length=100)
    status_sheet = models.CharField(max_length=100, blank=True)
    header_row = models.PositiveIntegerField(default=1)
    headers = models.JSONField(default=list)
    column_mapping = models.JSONField(default=dict, blank=True)
    caller_records = models.JSONField(default=list, blank=True)
    caller_mapping = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=12, choices=BatchStatus.choices, default=BatchStatus.STAGED)
    mapping_confirmed = models.BooleanField(default=False)
    discrepancies = models.JSONField(default=list, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    cycle = models.ForeignKey("allocations.AllocationCycle", null=True, blank=True, on_delete=models.PROTECT)
    caller_column_confirmed = models.BooleanField(default=False)
    discrepancies_acknowledged = models.BooleanField(default=False)
    committed_at = models.DateTimeField(null=True, blank=True)
    committed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"Import #{self.pk} — {self.original_filename}"

    @property
    def is_staged(self):
        return self.status == BatchStatus.STAGED


class ImportRow(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField(help_text="Row number in the source sheet.")
    raw_values = models.JSONField(default=dict, help_text="Every source column, as read.")
    overrides = models.JSONField(default=dict, blank=True, help_text="Values corrected by a coordinator.")
    values = models.JSONField(default=dict, blank=True, help_text="Normalised values used for import.")
    issues = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=RowStatus.choices, default=RowStatus.NEEDS_RESOLUTION)
    action = models.CharField(max_length=10, choices=RowAction.choices, blank=True, default=RowAction.AUTO)
    link_contact = models.ForeignKey(
        "contacts.Contact", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    skip_reason = models.CharField(max_length=300, blank=True)
    candidate_ids = models.JSONField(default=list, blank=True, help_text="Possible duplicate contacts.")
    contact = models.ForeignKey(
        "contacts.Contact", null=True, blank=True, on_delete=models.PROTECT, related_name="import_rows"
    )
    outcome = models.CharField(max_length=10, choices=RowOutcome.choices, blank=True)

    class Meta:
        ordering = ["batch", "row_number"]
        constraints = [models.UniqueConstraint(fields=["batch", "row_number"], name="one_row_per_source_row")]

    def __str__(self):
        return f"Row {self.row_number} of {self.batch}"

    def issues_at(self, level):
        return [i for i in self.issues if i["level"] == level]


class CallerAlias(models.Model):
    """Remembers that a name written in the workbook refers to a user."""

    alias = models.CharField(max_length=150, unique=True, help_text="Normalised name.")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="caller_aliases"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["alias"]

    def __str__(self):
        return f"{self.alias} → {self.user}"
