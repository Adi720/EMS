from django.urls import path

from . import views

app_name = "allocations"

urlpatterns = [
    path("", views.AllocationHomeView.as_view(), name="home"),
    path("change/", views.BulkChangeView.as_view(), name="change"),
    path("cycles/new/", views.CycleCreateView.as_view(), name="cycle_create"),
    path("operations/<int:pk>/", views.OperationDetailView.as_view(), name="operation"),
]
