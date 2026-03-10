from django.conf import settings

from wiki.comments.models import PageComment
from wiki.lib.permissions import is_system_owner
from wiki.pages.models import Page
from wiki.proposals.models import ChangeProposal


def inject_settings(request):
    """Inject specific settings into every template context."""
    return {
        "DEBUG": settings.DEBUG,
        "DEVELOPMENT": settings.DEVELOPMENT,
        "BASE_URL": settings.BASE_URL,
    }


def inject_review_pending(request):
    """Inject a boolean flag when the user has pending review items.

    For performance (runs on every request), only checks pages owned
    by the user rather than the full editable_page_ids() query.
    """
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return {}

    if is_system_owner(request.user):
        has_pending = (
            PageComment.objects.filter(
                status=PageComment.Status.PENDING
            ).exists()
            or ChangeProposal.objects.filter(
                status=ChangeProposal.Status.PENDING
            ).exists()
        )
    else:
        owned_ids = Page.objects.filter(owner=request.user).values_list(
            "id", flat=True
        )
        has_pending = (
            PageComment.objects.filter(
                page_id__in=owned_ids,
                status=PageComment.Status.PENDING,
            ).exists()
            or ChangeProposal.objects.filter(
                page_id__in=owned_ids,
                status=ChangeProposal.Status.PENDING,
            ).exists()
        )

    return {"has_review_pending": has_pending}
