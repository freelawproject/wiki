from django.urls import path

from . import views

urlpatterns = [
    path(
        "<int:file_id>/<str:filename>",
        views.file_serve,
        name="file_serve",
    ),
]
