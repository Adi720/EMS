from django.urls import path

from . import views

app_name = "contacts"

urlpatterns = [
    path("", views.ContactListView.as_view(), name="list"),
    path("new/", views.ContactCreateView.as_view(), name="create"),
    path("export/", views.ContactExportView.as_view(), name="export"),
    path("delete/", views.ContactDeleteView.as_view(), name="delete"),
    path("<int:pk>/", views.ContactDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.ContactUpdateView.as_view(), name="edit"),
    path("<int:pk>/status/", views.ContactStatusView.as_view(), name="status"),
    path("<int:pk>/reassign/", views.ContactReassignView.as_view(), name="reassign"),
]
