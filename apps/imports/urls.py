from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("", views.BatchListView.as_view(), name="list"),
    path("upload/", views.UploadView.as_view(), name="upload"),
    path("<int:pk>/", views.BatchDetailView.as_view(), name="detail"),
    path("<int:pk>/mapping/", views.MappingView.as_view(), name="mapping"),
    path("<int:pk>/callers/", views.CallerMappingView.as_view(), name="caller_mapping"),
    path("<int:pk>/create-callers/", views.CreateCallersView.as_view(), name="create_callers"),
    path("<int:pk>/rows/<int:row_id>/", views.RowEditView.as_view(), name="row_edit"),
    path("<int:pk>/commit/", views.CommitView.as_view(), name="commit"),
    path("<int:pk>/cancel/", views.CancelView.as_view(), name="cancel"),
    path("<int:pk>/rows.csv", views.RowReportView.as_view(), name="row_report"),
]
