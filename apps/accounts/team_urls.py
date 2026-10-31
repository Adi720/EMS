from django.urls import path

from . import team_views as views

app_name = "team"

urlpatterns = [
    path("", views.TeamListView.as_view(), name="list"),
    path("new/", views.TeamCreateView.as_view(), name="create"),
    path("<int:pk>/", views.TeamDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.TeamEditView.as_view(), name="edit"),
    path("<int:pk>/password/", views.TeamPasswordView.as_view(), name="password"),
    path("performance/", views.PerformanceView.as_view(), name="performance"),
    path("<int:pk>/leave/", views.TeamLeaveView.as_view(), name="leave"),
    path("<int:pk>/return/", views.TeamReturnView.as_view(), name="return"),
    path("<int:pk>/<str:action>/", views.TeamActiveView.as_view(), name="active"),
]
