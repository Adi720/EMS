from django.contrib import admin

from apps.allocations.admin import ReadOnlyAdmin

from .models import CallerAlias, ImportBatch


@admin.register(ImportBatch)
class ImportBatchAdmin(ReadOnlyAdmin):
    list_display = ("pk", "original_filename", "status", "uploaded_by", "uploaded_at")


@admin.register(CallerAlias)
class CallerAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "user", "created_by", "created_at")
    autocomplete_fields = ()
