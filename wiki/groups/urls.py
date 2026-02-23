from django.urls import path

from . import views

urlpatterns = [
    path("", views.group_list, name="group_list"),
    path("new/", views.group_create, name="group_create"),
    path("<int:pk>/", views.group_detail, name="group_detail"),
    path("<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("<int:pk>/delete/", views.group_delete, name="group_delete"),
    path(
        "<int:pk>/add-member/",
        views.group_add_member,
        name="group_add_member",
    ),
    path(
        "<int:pk>/remove-member/",
        views.group_remove_member,
        name="group_remove_member",
    ),
]
