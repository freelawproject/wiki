"""Comment notification helpers, called synchronously on comment events."""

from django.conf import settings
from django.core.mail import EmailMessage

from wiki.lib.users import display_name


def notify_owner_of_comment(comment_id):
    """Email the page owner that a new comment has been submitted."""
    from .models import PageComment

    comment = PageComment.objects.select_related(
        "page", "page__owner", "author"
    ).get(id=comment_id)

    page = comment.page
    owner = page.owner
    if not owner or not owner.email:
        return

    base = settings.BASE_URL
    review_url = (
        f"{base}/c/{page.content_path}/comments/{comment.id}/"
    )

    if comment.author:
        commenter_name = display_name(comment.author)
    else:
        commenter_name = comment.author_email or "An anonymous user"

    body = (
        f'{commenter_name} left a comment on "{page.title}".\n\n'
        f"Comment: {comment.message}\n\n"
        f"View: {review_url}"
    )

    msg = EmailMessage(
        subject=f'[FLP Wiki] New comment on "{page.title}"',
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[owner.email],
    )
    msg.send()


def notify_commenter_of_reply(comment_id):
    """Email the commenter when an editor replies."""
    from .models import PageComment

    comment = PageComment.objects.select_related(
        "page", "author", "replied_by"
    ).get(id=comment_id)

    # Determine recipient email
    if comment.author and comment.author.email:
        to_email = comment.author.email
    elif comment.author_email:
        to_email = comment.author_email
    else:
        return  # No way to notify

    page = comment.page
    base = settings.BASE_URL
    page_url = f"{base}{page.get_absolute_url()}"

    replier_name = (
        display_name(comment.replied_by)
        if comment.replied_by
        else "A page editor"
    )

    body = (
        f'{replier_name} replied to your comment on "{page.title}".\n\n'
        f"Reply: {comment.reply}\n\n"
        f"View page: {page_url}"
    )

    msg = EmailMessage(
        subject=f'[FLP Wiki] Reply to your comment on "{page.title}"',
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.send()
