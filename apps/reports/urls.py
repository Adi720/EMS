from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("monthly/", views.MonthlyReportView.as_view(), name="monthly"),
    path("monthly/export/", views.MonthlyExportView.as_view(), name="monthly_export"),
    path("sessions/<int:pk>/export/", views.SessionExportView.as_view(), name="session_export"),
]
