from django.urls import path

from . import views

app_name = "caller_requests"

urlpatterns = [
    path("", views.MyRequestsView.as_view(), name="mine"),
    path("manage/", views.ManageRequestsView.as_view(), name="manage"),
    path("<int:pk>/<str:decision>/", views.DecideRequestView.as_view(), name="decide"),
]
