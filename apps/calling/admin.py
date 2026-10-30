from django.contrib import admin

from apps.allocations.admin import ReadOnlyAdmin

from .models import CallAttempt, CallTask, EmsSession


@admin.register(EmsSession)
class EmsSessionAdmin(ReadOnlyAdmin):
    list_display = ("session_date", "title", "venue", "status")


@admin.register(CallTask)
class CallTaskAdmin(ReadOnlyAdmin):
    list_display = ("session", "contact", "caller", "status", "latest_outcome", "attempt_count")
    list_filter = ("session", "status", "latest_outcome")


@admin.register(CallAttempt)
class CallAttemptAdmin(ReadOnlyAdmin):
    list_display = ("attempted_at", "task", "outcome", "recorded_by")
