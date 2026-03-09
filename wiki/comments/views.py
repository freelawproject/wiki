from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from wiki.lib.page_utils import get_page_from_path
from wiki.lib.permissions import can_edit_page

from .forms import CommentReplyForm
from .models import PageComment
from .tasks import notify_commenter_of_reply


@login_required
def comment_detail(request, path, pk):
    """View a single comment (for editors/owners)."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        raise Http404

    comment = get_object_or_404(PageComment, pk=pk, page=page)
    reply_form = CommentReplyForm()

    return render(
        request,
        "comments/detail.html",
        {
            "page": page,
            "comment": comment,
            "reply_form": reply_form,
        },
    )


@require_POST
@login_required
def comment_reply(request, path, pk):
    """Reply to a comment (editor only)."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        raise Http404

    comment = get_object_or_404(
        PageComment,
        pk=pk,
        page=page,
        status=PageComment.Status.PENDING,
    )

    form = CommentReplyForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "comments/detail.html",
            {
                "page": page,
                "comment": comment,
                "reply_form": form,
            },
        )

    comment.reply = form.cleaned_data["reply"]
    comment.replied_by = request.user
    comment.replied_at = timezone.now()
    comment.save()

    notify_commenter_of_reply(comment.id)

    messages.success(request, "Reply sent.")
    return redirect("comment_detail", path=page.content_path, pk=pk)


@require_POST
@login_required
def comment_resolve(request, path, pk):
    """Resolve/dismiss a comment (editor only)."""
    page = get_page_from_path(path)

    if not can_edit_page(request.user, page):
        raise Http404

    comment = get_object_or_404(
        PageComment,
        pk=pk,
        page=page,
        status=PageComment.Status.PENDING,
    )

    comment.status = PageComment.Status.RESOLVED
    comment.resolved_by = request.user
    comment.resolved_at = timezone.now()
    comment.save()

    messages.success(request, "Comment resolved.")
    return redirect(page.get_absolute_url())
