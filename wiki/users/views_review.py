from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from wiki.comments.models import PageComment
from wiki.lib.permissions import editable_page_ids
from wiki.proposals.models import ChangeProposal


@login_required
def review_queue(request):
    """Unified review queue: pending proposals and comments across all
    pages the user can edit."""
    page_ids = editable_page_ids(request.user)

    proposals = list(
        ChangeProposal.objects.filter(
            page_id__in=page_ids,
            status=ChangeProposal.Status.PENDING,
        )
        .select_related("page", "proposed_by")
        .order_by("-created_at")
    )
    comments = list(
        PageComment.objects.filter(
            page_id__in=page_ids,
            status=PageComment.Status.PENDING,
        )
        .select_related("page", "author")
        .order_by("-created_at")
    )

    # Tag each item and merge into a single sorted list
    for p in proposals:
        p.item_type = "proposal"
    for c in comments:
        c.item_type = "comment"

    items = sorted(
        proposals + comments,
        key=lambda x: x.created_at,
        reverse=True,
    )

    return render(
        request,
        "users/review_queue.html",
        {
            "items": items,
            "proposal_count": len(proposals),
            "comment_count": len(comments),
        },
    )
