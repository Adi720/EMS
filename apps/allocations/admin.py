from django.contrib import admin

from .models import Allocation, AllocationCycle, AllocationOperation


class ReadOnlyAdmin(admin.ModelAdmin):
    """Allocation history is changed only through the application's audited workflows."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Allocation)
class AllocationAdmin(ReadOnlyAdmin):
    list_display = ("contact", "caller", "effective_from", "effective_to", "change_type")
    list_filter = ("change_type", "caller")
    search_fields = ("contact__full_name",)


@admin.register(AllocationOperation)
class AllocationOperationAdmin(ReadOnlyAdmin):
    list_display = ("performed_at", "kind", "effective_date", "change_count", "performed_by")


@admin.register(AllocationCycle)
class AllocationCycleAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "planned_end_date", "status")

    def has_delete_permission(self, request, obj=None):
        return False
