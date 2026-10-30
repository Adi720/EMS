from django.urls import path

from . import views

app_name = "calling"

# Internally a congregation is an "EmsSession"; users see "EMS Congregation (d/m/yy)".
urlpatterns = [
    path("congregations/", views.SessionListView.as_view(), name="session_list"),
    path("congregations/new/", views.SessionCreateView.as_view(), name="session_create"),
    path("congregations/start-week/", views.StartWeeklyCallingView.as_view(), name="start_week"),
    path("congregations/<int:pk>/", views.SessionDetailView.as_view(), name="session_detail"),
    path("congregations/<int:pk>/edit/", views.SessionUpdateView.as_view(), name="session_edit"),
    path(
        "congregations/<int:pk>/<str:action>/",
        views.SessionActionView.as_view(),
        name="session_action",
    ),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="task_detail"),
    path("tasks/<int:pk>/quick/", views.QuickAttemptView.as_view(), name="quick_attempt"),
]
