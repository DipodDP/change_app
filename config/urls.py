from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from exchanges.forms import StyledLoginForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(authentication_form=StyledLoginForm),
        name="login",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("exchanges.urls")),
]
