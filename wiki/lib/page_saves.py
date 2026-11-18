"""Saving a page and the bookkeeping that goes with it.

Every path that creates or edits a page (the web editor, the JSON API) goes
through ``save_new_page`` or ``save_page_edit`` so that each save links its
uploads, records a revision, keeps redirects for a moved URL, subscribes the
editor, and tells subscribers and @-mentioned users.
"""

import re

from django.db import transaction

from wiki.lib.page_utils import record_page_move
from wiki.pages.models import FileUpload, Page
from wiki.subscriptions.models import PageSubscription
from wiki.subscriptions.tasks import notify_subscribers, process_mentions

FILE_REF_RE = re.compile(r"/files/(\d+)/")

# Matches @username (word chars only, not followed by @)
_MENTION_RE = re.compile(r"@([a-zA-Z][a-zA-Z0-9._-]*)")


class EditConflict(Exception):
    """The page has a newer revision than the one the edit was based on."""

    def __init__(self, current_revision):
        super().__init__(current_revision)
        self.current_revision = current_revision


def current_revision_number(page):
    """The number of the page's latest revision, or 0 if it has none."""
    latest = page.revisions.order_by("-revision_number").first()
    return latest.revision_number if latest else 0


def extract_mentions(text):
    """Extract @mention usernames from text."""
    return list(set(_MENTION_RE.findall(text or "")))


def link_uploads_to_page(page, user):
    """Link FileUpload records referenced in page content to this page.

    Parses /files/<id>/ references from the page's markdown content and
    sets FileUpload.page for any unlinked uploads that the editing user
    owns.  Also unlinks uploads previously attached to this page that are
    no longer referenced by the current content *or* any past revision
    (so that revisions remain restorable).

    Security: only orphaned uploads belonging to ``user`` are linked,
    preventing a user from claiming another user's upload by guessing
    its ID and embedding it in their page.
    """
    referenced_ids = set(int(m) for m in FILE_REF_RE.findall(page.content))

    if referenced_ids:
        FileUpload.objects.filter(
            id__in=referenced_ids, page__isnull=True, uploaded_by=user
        ).update(page=page)

    # Collect file IDs referenced by any revision of this page.
    revision_ids = set()
    for content in page.revisions.values_list("content", flat=True):
        revision_ids.update(int(m) for m in FILE_REF_RE.findall(content))

    # Only unlink uploads not referenced by current content OR any
    # past revision, so that older revisions can still be restored.
    keep_ids = referenced_ids | revision_ids
    stale = FileUpload.objects.filter(page=page).exclude(id__in=keep_ids)
    stale.update(page=None)


def _process_mentions(page, user, grant_access):
    """Notify users @-mentioned in the page or its change message, granting
    the access in ``grant_access`` ({username: "view"|"edit"})."""
    mentioned = extract_mentions(page.content)
    mentioned += extract_mentions(page.change_message)
    if mentioned:
        process_mentions(
            page.id, user.id, mentioned, grant_access_to=grant_access
        )


def save_new_page(page, user, grant_access=None):
    """Save a new, unsaved ``page`` as ``user``'s, with its first revision.

    The caller sets the page's fields (directory included) beforehand.
    Returns the revision.
    """
    page.owner = user
    page.created_by = user
    page.updated_by = user
    with transaction.atomic():
        page.save()
        link_uploads_to_page(page, user)
        rev = page.create_revision(
            user, page.change_message or "Initial creation"
        )
        PageSubscription.objects.get_or_create(user=user, page=page)

    _process_mentions(page, user, grant_access)
    notify_subscribers(page.id, user.id, page.change_message, action="created")
    return rev


def save_page_edit(
    page,
    user,
    *,
    old_directory,
    old_slug,
    grant_access=None,
    base_revision=None,
):
    """Save ``user``'s edit to ``page`` as a new revision.

    ``old_directory`` and ``old_slug`` are the page's values from before the
    edit, so a URL the edit changed leaves a redirect behind. With
    ``base_revision``, the save is refused with ``EditConflict`` (and nothing
    is written) if the page has moved past that revision in the meantime.
    Returns the new revision.
    """
    page.updated_by = user
    with transaction.atomic():
        if base_revision is not None:
            # Hold the page's row so a concurrent edit can't slip in between
            # the check and the save.
            Page.objects.select_for_update().filter(pk=page.pk).first()
            current = current_revision_number(page)
            if current != base_revision:
                raise EditConflict(current)
        page.save()
        link_uploads_to_page(page, user)
        record_page_move(page, old_directory, old_slug)
        rev = page.create_revision(user)
        PageSubscription.objects.get_or_create(user=user, page=page)

    notify_subscribers(
        page.id,
        user.id,
        page.change_message,
        prev_rev=rev.revision_number - 1 if rev.revision_number > 1 else None,
        new_rev=rev.revision_number,
    )
    _process_mentions(page, user, grant_access)
    return rev
