from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("exchange/new/", views.exchange_create, name="exchange-create"),
    path("exchange/<int:pk>/edit/", views.exchange_edit, name="exchange-edit"),
    path("exchange/<int:pk>/delete/", views.exchange_delete, name="exchange-delete"),
    path("route/new/", views.route_create, name="route-create"),
    path("route/<int:pk>/edit/", views.route_edit, name="route-edit"),
    path("route/<int:pk>/delete/", views.route_delete, name="route-delete"),
    path("reset/", views.reset_data, name="reset-data"),
]
