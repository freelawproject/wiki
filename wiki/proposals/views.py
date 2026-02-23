from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from wiki.lib.permissions import can_edit_page, can_view_page
from wiki.pages.models import Page, PageRevision

from .forms import ProposalForm
from .models import ChangeProposal
from .tasks import notify_owner_of_proposal, notify_proposer_of_decision


def _get_page_from_path(path):
    """Resolve a content path to a Page object."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    return get_object_or_404(Page, slug=slug)


def propose_changes(request, path):
    """Submit a proposed change to a page."""
    page = _get_page_from_path(path)

    if not can_view_page(request.user, page):
        raise Http404

    # If user can edit, redirect to the edit page instead
    if can_edit_page(request.user, page):
        return redirect("page_edit", path=page.content_path)

    form = ProposalForm(
        request.POST or None,
        is_authenticated=request.user.is_authenticated,
        initial={
            "proposed_title": page.title,
            "proposed_content": page.content,
        },
    )

    if request.method == "POST" and form.is_valid():
        proposal = form.save(commit=False)
        proposal.page = page
        if request.user.is_authenticated:
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
        "proposals/propose.html",
        {
            "form": form,
            "page": page,
        },
    )


@login_required
def proposal_list(request, path):
    """List proposals for a page (for editors/owners)."""
    page = _get_page_from_path(path)

    if not can_edit_page(request.user, page):
        messages.error(
            request,
            "You don't have permission to review proposals for this page.",
        )
        return redirect(page.get_absolute_url())

    pending = page.proposals.filter(
        status=ChangeProposal.Status.PENDING
    ).select_related("proposed_by")
    reviewed = page.proposals.exclude(
        status=ChangeProposal.Status.PENDING
    ).select_related("proposed_by", "reviewed_by")

    return render(
        request,
        "proposals/list.html",
        {
            "page": page,
            "pending": pending,
            "reviewed": reviewed,
        },
    )


@login_required
def proposal_review(request, path, pk):
    """Review a single proposal with diff view."""
    page = _get_page_from_path(path)

    if not can_edit_page(request.user, page):
        messages.error(
            request,
            "You don't have permission to review proposals.",
        )
        return redirect(page.get_absolute_url())

    proposal = get_object_or_404(ChangeProposal, pk=pk, page=page)

    from wiki.pages.diff_utils import unified_diff

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
    page = _get_page_from_path(path)

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
    page.save()

    # Create revision
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

    # Mark proposal as accepted
    proposal.status = ChangeProposal.Status.ACCEPTED
    proposal.reviewed_by = request.user
    proposal.reviewed_at = timezone.now()
    proposal.save()

    # Notify proposer and subscribers
    notify_proposer_of_decision(proposal.id)

    from wiki.subscriptions.tasks import notify_subscribers

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
    page = _get_page_from_path(path)

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
