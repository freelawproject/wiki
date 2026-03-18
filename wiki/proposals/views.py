from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from wiki.comments.forms import CommentForm
from wiki.comments.models import PageComment
from wiki.comments.tasks import notify_owner_of_comment
from wiki.lib.page_utils import get_page_from_path
from wiki.lib.permissions import can_edit_page, can_view_page
from wiki.pages.diff_utils import unified_diff
from wiki.pages.models import PageRevision
from wiki.subscriptions.tasks import notify_subscribers

from .forms import ProposalForm
from .models import ChangeProposal
from .tasks import notify_owner_of_proposal, notify_proposer_of_decision


def page_feedback(request, path):
    """Unified feedback page: comment or propose changes."""
    page = get_page_from_path(path)

    if not can_view_page(request.user, page):
        raise Http404

    # Editors/owners cannot submit feedback — they can edit directly
    if can_edit_page(request.user, page):
        raise Http404

    is_auth = request.user.is_authenticated
    comment_form = CommentForm(is_authenticated=is_auth)
    proposal_form = ProposalForm(
        is_authenticated=is_auth,
        initial={
            "proposed_title": page.title,
            "proposed_content": page.content,
        },
    )
    active_tab = "comment"

    if request.method == "POST":
        if "submit_comment" in request.POST:
            comment_form = CommentForm(request.POST, is_authenticated=is_auth)
            if comment_form.is_valid():
                comment = comment_form.save(commit=False)
                comment.page = page
                if is_auth:
                    comment.author = request.user
                comment.save()
                notify_owner_of_comment(comment.id)
                messages.success(request, "Your comment has been submitted.")
                return redirect(page.get_absolute_url())
        elif "submit_proposal" in request.POST:
            active_tab = "propose"
            proposal_form = ProposalForm(
                request.POST, is_authenticated=is_auth
            )
            if proposal_form.is_valid():
                proposal = proposal_form.save(commit=False)
                proposal.page = page
                if is_auth:
                    proposal.proposed_by = request.user
                proposal.save()
                notify_owner_of_proposal(proposal.id)
                messages.success(
                    request,
                    "Your proposed changes have been submitted for review.",
                )
                return redirect(page.get_absolute_url())

    return render(
        request,
        "proposals/feedback.html",
        {
            "page": page,
            "comment_form": comment_form,
            "proposal_form": proposal_form,
            "active_tab": active_tab,
        },
    )


@login_required
def proposal_list(request, path):
    """List proposals and comments for a page (for editors/owners)."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        messages.error(
            request,
            "You don't have permission to review feedback for this page.",
        )
        return redirect(page.get_absolute_url())

    pending_proposals = page.proposals.filter(
        status=ChangeProposal.Status.PENDING
    ).select_related("proposed_by")
    reviewed_proposals = page.proposals.exclude(
        status=ChangeProposal.Status.PENDING
    ).select_related("proposed_by", "reviewed_by")

    pending_comments = page.comments.filter(
        status=PageComment.Status.PENDING
    ).select_related("author")
    resolved_comments = page.comments.exclude(
        status=PageComment.Status.PENDING
    ).select_related("author", "resolved_by")

    return render(
        request,
        "proposals/list.html",
        {
            "page": page,
            "pending_proposals": pending_proposals,
            "reviewed_proposals": reviewed_proposals,
            "pending_comments": pending_comments,
            "resolved_comments": resolved_comments,
        },
    )


@login_required
def proposal_review(request, path, pk):
    """Review a single proposal with diff view."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        messages.error(
            request,
            "You don't have permission to review proposals.",
        )
        return redirect(page.get_absolute_url())

    proposal = get_object_or_404(ChangeProposal, pk=pk, page=page)

    diff_html = unified_diff(page.content, proposal.proposed_content)

    return render(
        request,
        "proposals/review.html",
        {
            "page": page,
            "proposal": proposal,
            "diff_html": diff_html,
        },
    )


@require_POST
@login_required
def proposal_accept(request, path, pk):
    """Accept a proposal, applying changes to the page."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        messages.error(
            request, "You don't have permission to accept proposals."
        )
        return redirect(page.get_absolute_url())

    proposal = get_object_or_404(
        ChangeProposal,
        pk=pk,
        page=page,
        status=ChangeProposal.Status.PENDING,
    )

    # Allow reviewer to tweak content before accepting
    new_title = request.POST.get("title", "").strip()
    new_content = request.POST.get("content", "").strip()

    page.title = new_title or proposal.proposed_title
    page.content = new_content or proposal.proposed_content
    page.change_message = f"Accepted proposal: {proposal.change_message}"
    page.updated_by = request.user

    with transaction.atomic():
        page.save()
        last_rev = page.revisions.order_by("-revision_number").first()
        rev_num = (last_rev.revision_number + 1) if last_rev else 1
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message=page.change_message,
            revision_number=rev_num,
            created_by=request.user,
        )
        proposal.status = ChangeProposal.Status.ACCEPTED
        proposal.reviewed_by = request.user
        proposal.reviewed_at = timezone.now()
        proposal.save()

    notify_proposer_of_decision(proposal.id)
    notify_subscribers(
        page.id,
        request.user.id,
        page.change_message,
        prev_rev=rev_num - 1 if rev_num > 1 else None,
        new_rev=rev_num,
    )

    messages.success(request, f'Proposal accepted and "{page.title}" updated.')
    return redirect(page.get_absolute_url())


@require_POST
@login_required
def proposal_deny(request, path, pk):
    """Deny a proposal with an optional reason."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        messages.error(request, "You don't have permission to deny proposals.")
        return redirect(page.get_absolute_url())

    proposal = get_object_or_404(
        ChangeProposal,
        pk=pk,
        page=page,
        status=ChangeProposal.Status.PENDING,
    )

    proposal.status = ChangeProposal.Status.DENIED
    proposal.reviewed_by = request.user
    proposal.reviewed_at = timezone.now()
    proposal.denial_reason = request.POST.get("denial_reason", "")
    proposal.save()

    notify_proposer_of_decision(proposal.id)

    messages.success(request, "Proposal denied.")
    return redirect(page.get_absolute_url())
