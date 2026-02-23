from django.urls import path

from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("verify/", views.verify_view, name="verify"),
]
