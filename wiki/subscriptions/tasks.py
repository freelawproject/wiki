"""Subscription notification helpers, called synchronously on page save."""

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMessage, send_mail
from django.core.signing import Signer
from django.urls import reverse

from wiki.lib.permissions import can_view_page
from wiki.lib.users import display_name
from wiki.pages.models import Page, PagePermission

from .utils import get_subscriber_info_for_page


def notify_subscribers(
    page_id, editor_id, change_message, prev_rev=None, new_rev=None
):
    """Notify all subscribers about a page change.

    Called synchronously after page save.
    """
    page = Page.objects.get(id=page_id)
    editor = User.objects.get(id=editor_id)

    page_sub_user_ids, dir_sub_mapping = get_subscriber_info_for_page(page)

    signer = Signer()
    base = settings.BASE_URL
    page_url = (
        f"{base}{reverse('resolve_path', kwargs={'path': page.content_path})}"
    )

    # Build diff line if we have both revision numbers
    diff_line = ""
    if prev_rev is not None and new_rev is not None and prev_rev >= 1:
        diff_path = reverse(
            "page_diff",
            kwargs={"path": page.content_path, "v1": prev_rev, "v2": new_rev},
        )
        diff_url = f"{base}{diff_path}"
        diff_line = f"Diff: {diff_url}\n\n"

    all_user_ids = page_sub_user_ids | set(dir_sub_mapping.keys())
    if not all_user_ids:
        return

    users = {
        u.id: u
        for u in User.objects.filter(id__in=all_user_ids).select_related(
            "profile"
        )
    }

    for uid, user in users.items():
        # Don't notify the editor themselves
        if uid == editor_id:
            continue

        # Only notify users who can view the page
        if not can_view_page(user, page):
            continue

        if uid in page_sub_user_ids:
            # Direct page subscriber (page-level override takes priority)
            token = signer.sign(f"{uid}:{page.id}")
            unsub_landing = (
                f"{base}{reverse('unsubscribe', kwargs={'token': token})}"
            )
            unsub_one_click = f"{base}{reverse('unsubscribe_one_click', kwargs={'token': token})}"

            body = (
                f"{display_name(editor)} "
                f'updated "{page.title}".\n\n'
                f"Change: {change_message or 'No description'}\n\n"
                f"View: {page_url}\n\n"
                f"{diff_line}"
                f"Unsubscribe: {unsub_landing}"
            )

            msg = EmailMessage(
                subject=f'[FLP Wiki] "{page.title}" was updated',
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                headers={
                    "List-Unsubscribe": f"<{unsub_one_click}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            )
            msg.send()
        elif uid in dir_sub_mapping:
            # Directory-based subscriber
            directory = dir_sub_mapping[uid]
            page_token = signer.sign(f"{uid}:{page.id}")
            dir_token = signer.sign(f"d:{uid}:{directory.id}")
            page_unsub = (
                f"{base}{reverse('unsubscribe', kwargs={'token': page_token})}"
            )
            dir_unsub = (
                f"{base}{reverse('unsubscribe', kwargs={'token': dir_token})}"
            )
            page_unsub_one_click = f"{base}{reverse('unsubscribe_one_click', kwargs={'token': page_token})}"

            body = (
                f"{display_name(editor)} "
                f'updated "{page.title}".\n\n'
                f"Change: {change_message or 'No description'}\n\n"
                f"View: {page_url}\n\n"
                f"{diff_line}"
                f'You received this because you\'re subscribed to "{directory.title}".\n\n'
                f"Unsubscribe from this page: {page_unsub}\n"
                f"Unsubscribe from {directory.title}: {dir_unsub}"
            )

            msg = EmailMessage(
                subject=f'[FLP Wiki] "{page.title}" was updated',
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                headers={
                    "List-Unsubscribe": f"<{page_unsub_one_click}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            )
            msg.send()


def _get_content_snippet(content, username, context_lines=2):
    """Extract lines around an @username mention for email context."""
    lines = (content or "").splitlines()
    for i, line in enumerate(lines):
        if f"@{username}" in line:
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            return "\n".join(lines[start:end])
    return ""


def process_mentions(
    page_id, editor_id, mentioned_usernames, grant_access_to=None
):
    """Process @-mentions: grant access and notify mentioned users.

    Does NOT auto-subscribe — users choose to subscribe themselves.

    Args:
        page_id: The page being edited
        editor_id: The user who made the edit
        mentioned_usernames: List of username strings (before @)
        grant_access_to: Optional dict mapping {username: "view"|"edit"}
            for per-user access grants
    """
    if not mentioned_usernames:
        return

    page = Page.objects.get(id=page_id)
    editor = User.objects.get(id=editor_id)
    base = settings.BASE_URL
    page_url = (
        f"{base}{reverse('resolve_path', kwargs={'path': page.content_path})}"
    )
    grant_map = grant_access_to or {}

    for uname in mentioned_usernames:
        email = f"{uname}@free.law"
        user = User.objects.filter(email=email).first()
        if not user or user.id == editor_id:
            continue

        # Grant access if requested (per-user level)
        access_level = grant_map.get(uname)
        if access_level == "edit":
            PagePermission.objects.get_or_create(
                page=page,
                user=user,
                permission_type=PagePermission.PermissionType.EDIT,
            )
        elif access_level == "view":
            PagePermission.objects.get_or_create(
                page=page,
                user=user,
                permission_type=PagePermission.PermissionType.VIEW,
            )

        # Only notify users who can view the page
        if not can_view_page(user, page):
            continue

        # Build email with content snippet
        snippet = _get_content_snippet(page.content, uname)
        snippet_text = ""
        if snippet:
            snippet_text = f"\nContext:\n{snippet}\n"

        send_mail(
            subject=(
                f"[FLP Wiki] {display_name(editor)} "
                f'mentioned you in "{page.title}"'
            ),
            message=(
                f"{display_name(editor)} mentioned you in "
                f'"{page.title}".\n'
                f"{snippet_text}\n"
                f"View: {page_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
