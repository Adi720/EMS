from django.urls import path

from apps.calling.views import CallerDashboardView, MyReportView
from apps.reports.views import CoordinatorDashboardView

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("my-calls/", CallerDashboardView.as_view(), name="caller_dashboard"),
    path("my-report/", MyReportView.as_view(), name="my_report"),
    path("coordinator/", CoordinatorDashboardView.as_view(), name="coordinator_dashboard"),
    path("healthz/", views.healthz, name="healthz"),
]
