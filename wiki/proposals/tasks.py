"""Proposal notification helpers, called synchronously on proposal events."""

from django.conf import settings
from django.core.mail import EmailMessage


def _display_name(user):
    """Return display name for a user, never showing a full email."""
    if hasattr(user, "profile"):
        try:
            name = user.profile.display_name
            if name:
                return name
        except Exception:
            pass
    if user.email and "@" in user.email:
        return user.email.split("@")[0]
    return user.username.split("@")[0]


def notify_owner_of_proposal(proposal_id):
    """Email the page owner that a new proposal has been submitted."""
    from .models import ChangeProposal

    proposal = ChangeProposal.objects.select_related(
        "page", "page__owner", "proposed_by"
    ).get(id=proposal_id)

    page = proposal.page
    owner = page.owner
    if not owner or not owner.email:
        return

    base = settings.BASE_URL
    review_url = f"{base}/c/{page.content_path}/proposals/{proposal.id}/"

    if proposal.proposed_by:
        proposer_name = _display_name(proposal.proposed_by)
    else:
        proposer_name = proposal.proposer_email or "An anonymous user"

    body = (
        f'{proposer_name} proposed changes to "{page.title}".\n\n'
        f"Change: {proposal.change_message}\n\n"
        f"Review: {review_url}"
    )

    msg = EmailMessage(
        subject=f'[FLP Wiki] Change proposed for "{page.title}"',
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[owner.email],
    )
    msg.send()


def notify_proposer_of_decision(proposal_id):
    """Email the proposer about the accept/deny decision."""
    from .models import ChangeProposal

    proposal = ChangeProposal.objects.select_related(
        "page", "proposed_by", "reviewed_by"
    ).get(id=proposal_id)

    # Determine recipient email
    if proposal.proposed_by and proposal.proposed_by.email:
        to_email = proposal.proposed_by.email
    elif proposal.proposer_email:
        to_email = proposal.proposer_email
    else:
        return  # No way to notify

    page = proposal.page
    base = settings.BASE_URL
    page_url = f"{base}{page.get_absolute_url()}"

    reviewer_name = (
        _display_name(proposal.reviewed_by)
        if proposal.reviewed_by
        else "A reviewer"
    )

    if proposal.status == ChangeProposal.Status.ACCEPTED:
        subject = f'[FLP Wiki] Your proposal for "{page.title}" was accepted'
        body = (
            f"{reviewer_name} accepted your proposed changes to "
            f'"{page.title}".\n\n'
            f"View: {page_url}"
        )
    else:
        subject = f'[FLP Wiki] Your proposal for "{page.title}" was denied'
        reason = proposal.denial_reason or "No reason provided."
        body = (
            f"{reviewer_name} denied your proposed changes to "
            f'"{page.title}".\n\n'
            f"Reason: {reason}\n\n"
            f"View: {page_url}"
        )

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.send()
