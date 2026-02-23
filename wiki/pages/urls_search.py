from django.urls import path

from . import views_search

urlpatterns = [
    path("", views_search.search_view, name="search"),
]
