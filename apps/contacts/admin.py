from django.contrib import admin

from .models import Contact, ContactStatusChange


class ReadOnlyHistoryInline(admin.TabularInline):
    model = ContactStatusChange
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in ContactStatusChange._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    """Inspection only. Status changes must go through the app so history is recorded."""

    list_display = ("full_name", "area", "status", "registration_date")
    list_filter = ("status",)
    search_fields = ("full_name", "area", "phone_primary")
    readonly_fields = (
        "status",
        "status_since",
        "review_date",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )
    inlines = [ReadOnlyHistoryInline]

    def has_delete_permission(self, request, obj=None):
        return False
