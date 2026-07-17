from django.urls import path

from . import views

urlpatterns = [
    path("pages/", views.list_pages, name="api_list_pages"),
    path("search/", views.search, name="api_search"),
    # Catch-all path segment — must stay last.
    path("pages/<path:path>", views.read_page, name="api_read_page"),
]
