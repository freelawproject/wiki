from django.urls import path

from . import views

urlpatterns = [
    path(
        "<str:token>/",
        views.unsubscribe_landing,
        name="unsubscribe",
    ),
    path(
        "<str:token>/one-click/",
        views.unsubscribe_one_click,
        name="unsubscribe_one_click",
    ),
]
