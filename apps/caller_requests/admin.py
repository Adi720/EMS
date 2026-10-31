from django.contrib import admin

from .models import CallerRequest


@admin.register(CallerRequest)
class CallerRequestAdmin(admin.ModelAdmin):
    """Inspection only; requests are decided in the app."""

    list_display = ("created_at", "kind", "contact_name", "raised_by", "status")
    list_filter = ("status", "kind")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
