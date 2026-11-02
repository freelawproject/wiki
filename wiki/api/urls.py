from django.urls import path

from . import views

urlpatterns = [
    path("pages/", views.page_list, name="api_page_list"),
    path("search/", views.page_search, name="api_search"),
    path("pages/<path:path>", views.page_detail, name="api_page_detail"),
]
