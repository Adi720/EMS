from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "email", "roles", "is_active", "last_login")
    list_filter = ("is_active", "groups", "is_staff", "is_superuser")

    @admin.display(description="Roles")
    def roles(self, obj):
        return ", ".join(sorted(obj.groups.values_list("name", flat=True))) or "—"
