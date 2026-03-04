from django.urls import path

from . import views_review

urlpatterns = [
    path("", views_review.review_queue, name="review_queue"),
]
