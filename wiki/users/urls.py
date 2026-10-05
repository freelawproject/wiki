from django.urls import path

from . import views, views_oidc

urlpatterns = [
    path("", views.login_view, name="login"),
    path("verify/", views.verify_view, name="verify"),
    path(
        "courtlistener/",
        views_oidc.CourtListenerLoginView.as_view(),
        name="oidc_authentication_init",
    ),
    path(
        "courtlistener/callback/",
        views_oidc.CourtListenerCallbackView.as_view(),
        name="oidc_authentication_callback",
    ),
]
