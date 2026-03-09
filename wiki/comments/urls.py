from django.urls import path

from . import views

urlpatterns = [
    path(
        "<path:path>/comments/<int:pk>/",
        views.comment_detail,
        name="comment_detail",
    ),
    path(
        "<path:path>/comments/<int:pk>/reply/",
        views.comment_reply,
        name="comment_reply",
    ),
    path(
        "<path:path>/comments/<int:pk>/resolve/",
        views.comment_resolve,
        name="comment_resolve",
    ),
]
