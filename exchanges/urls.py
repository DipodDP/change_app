from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("exchange/new/", views.exchange_create, name="exchange-create"),
    path("exchange/<int:pk>/edit/", views.exchange_edit, name="exchange-edit"),
    path("exchange/<int:pk>/delete/", views.exchange_delete, name="exchange-delete"),
    path("reset/", views.reset_data, name="reset-data"),
]
