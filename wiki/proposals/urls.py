from django.urls import path

from . import views

urlpatterns = [
    path(
        "<path:path>/propose/",
        views.propose_changes,
        name="propose_changes",
    ),
    path(
        "<path:path>/proposals/",
        views.proposal_list,
        name="proposal_list",
    ),
    path(
        "<path:path>/proposals/<int:pk>/",
        views.proposal_review,
        name="proposal_review",
    ),
    path(
        "<path:path>/proposals/<int:pk>/accept/",
        views.proposal_accept,
        name="proposal_accept",
    ),
    path(
        "<path:path>/proposals/<int:pk>/deny/",
        views.proposal_deny,
        name="proposal_deny",
    ),
]
