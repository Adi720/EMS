from django.conf import settings
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "EMS Seva administration"
admin.site.site_title = "EMS Seva admin"

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("contacts/", include("apps.contacts.urls")),
    path("team/", include("apps.accounts.team_urls")),
    path("allocations/", include("apps.allocations.urls")),
    path("calling/", include("apps.calling.urls")),
    path("reports/", include("apps.reports.urls")),
    path("imports/", include("apps.imports.urls")),
    path("audit/", include("apps.audit.urls")),
    path("", include("apps.core.urls")),
]
