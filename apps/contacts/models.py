from django.conf import settings
from django.db import models

from apps.core.phones import display_phone


class ContactStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    TEMP_UNAVAILABLE = "temp_unavailable", "Temporarily unavailable"
    INACTIVE = "inactive", "Inactive / moved away"
    DO_NOT_CALL = "do_not_call", "Do not call"


class StatusReason(models.TextChoices):
    CREATED = "created", "Contact created"
    IMPORTED = "imported", "Imported from workbook"
    TEMPORARILY_AWAY = "temporarily_away", "Temporarily away (travel, exams, health…)"
    MOVED_AWAY = "moved_away", "Moved away"
    CANNOT_ATTEND = "cannot_attend", "No longer able to attend"
    REQUESTED_NO_CALLS = "requested_no_calls", "Asked not to be called"
    AVAILABLE_AGAIN = "available_again", "Available again"
    CORRECTION = "correction", "Correction of an earlier status"
    OTHER = "other", "Other"


class AppendOnlyModel(models.Model):
    """History rows are written once; the application never changes or deletes them."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None and not kwargs.pop("_allow_update", False):
            raise ValueError(f"{type(self).__name__} records are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(f"{type(self).__name__} records cannot be deleted.")


class Contact(models.Model):
    full_name = models.CharField(max_length=150)
    phone_primary = models.CharField("Phone", max_length=20, db_index=True, help_text="Stored in E.164 form.")
    phone_secondary = models.CharField("Secondary phone", max_length=20, blank=True)
    area = models.CharField(max_length=150)
    registration_date = models.DateField(help_text="Date the contact was collected at the EMS stall.")
    qualification = models.CharField(max_length=150, blank=True)
    collected_by_name = models.CharField(
        "Collected by", max_length=150, blank=True, help_text="Stall seva member (free text)."
    )
    notes = models.TextField(blank=True, max_length=2000)

    status = models.CharField(
        max_length=20, choices=ContactStatus.choices, default=ContactStatus.ACTIVE, db_index=True
    )
    status_since = models.DateField(null=True, blank=True)
    review_date = models.DateField(
        null=True, blank=True, help_text="For temporarily unavailable contacts: when to check again."
    )
    legacy_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["full_name", "id"]
        indexes = [models.Index(fields=["area"]), models.Index(fields=["phone_secondary"])]

    def __str__(self):
        return self.full_name

    @property
    def is_callable(self):
        return self.status == ContactStatus.ACTIVE

    @property
    def is_do_not_call(self):
        return self.status == ContactStatus.DO_NOT_CALL

    @property
    def phone_display(self):
        return display_phone(self.phone_primary)

    @property
    def phone_secondary_display(self):
        return display_phone(self.phone_secondary)


class ContactStatusChange(AppendOnlyModel):
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=20, choices=ContactStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=ContactStatus.choices)
    reason_category = models.CharField(max_length=30, choices=StatusReason.choices)
    reason_text = models.TextField(blank=True, max_length=1000)
    effective_date = models.DateField()
    review_date = models.DateField(null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.contact}: {self.from_status or '—'} → {self.to_status}"
