"""Requests a caller raises for a coordinator, e.g. "this Saint is unable to attend"."""

from django.conf import settings
from django.db import models


class RequestKind(models.TextChoices):
    UNABLE_TO_ATTEND = "unable_to_attend", "Saint is unable to attend EMS"
    WRONG_NUMBER = "wrong_number", "Wrong or changed mobile number"
    CHANGE_CALLER = "change_caller", "Please give this Saint to another caller"
    ON_LEAVE = "on_leave", "I need a break (On Leave)"
    OTHER = "other", "Something else"


# Kinds that are about one particular Saint.
NEEDS_SAINT = frozenset({RequestKind.UNABLE_TO_ATTEND, RequestKind.WRONG_NUMBER, RequestKind.CHANGE_CALLER})


class RequestStatus(models.TextChoices):
    PENDING = "pending", "Waiting"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Not approved"


class CallerRequest(models.Model):
    kind = models.CharField(max_length=30, choices=RequestKind.choices)
    contact = models.ForeignKey(
        "contacts.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="requests"
    )
    contact_name = models.CharField(max_length=150, blank=True, help_text="Kept if the Saint is deleted.")
    reason = models.TextField(max_length=1000)
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10, choices=RequestStatus.choices, default=RequestStatus.PENDING, db_index=True
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        about = f" — {self.contact_name}" if self.contact_name else ""
        return f"{self.get_kind_display()}{about}"

    @property
    def is_pending(self):
        return self.status == RequestStatus.PENDING
