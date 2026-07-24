"""Per-page revision-history feed.

Served at ``/c/<path>.rss`` mirroring the ``.md`` raw-markdown URL. The
payload is Atom: readers detect the format from the XML content, not
the extension, and ``.rss`` is the extension people actually guess.
"""

from django.contrib.syndication.views import Feed
from django.http import Http404
from django.urls import reverse
from django.utils.feedgenerator import Atom1Feed

from wiki.lib.page_utils import page_at_path
from wiki.lib.permissions import can_view_page
from wiki.lib.users import display_name

FEED_ITEM_LIMIT = 30


class PageHistoryFeed(Feed):
    feed_type = Atom1Feed

    def get_object(self, request, path):
        page = page_at_path(path)
        # Probe-resistant: unviewable == missing (matches page_history).
        if page is None or not can_view_page(request.user, page):
            raise Http404
        # Feed readers can't log in, so anonymous requests 404 instead
        # of redirecting to login; authenticated users may fetch even
        # when history isn't public (mirrors the history page).
        if not request.user.is_authenticated and not page.history_is_public:
            raise Http404
        return page

    def title(self, obj):
        return f"{obj.title} — revision history — FLP Wiki"

    def link(self, obj):
        return reverse("page_history", kwargs={"path": obj.content_path})

    def description(self, obj):
        return f'Changes to "{obj.title}" on the FLP Wiki.'

    subtitle = description  # Atom uses <subtitle>, not <description>

    def items(self, obj):
        revs = list(
            obj.revisions.select_related("created_by")[:FEED_ITEM_LIMIT]
        )
        for rev in revs:
            rev.page = obj  # pre-warm the FK cache; item_link needs it
        return revs

    def item_title(self, item):
        return (
            f"Revision {item.revision_number}: "
            f"{item.change_message or 'Updated'}"
        )

    def item_description(self, item):
        author = (
            display_name(item.created_by) if item.created_by else "Unknown"
        )
        return f"{author}: {item.change_message or '(no change message)'}"

    def item_link(self, item):
        if item.revision_number > 1:
            return reverse(
                "page_diff",
                kwargs={
                    "path": item.page.content_path,
                    "v1": item.revision_number - 1,
                    "v2": item.revision_number,
                },
            )
        # Revision 1 has nothing to diff against — link to history.
        return reverse(
            "page_history", kwargs={"path": item.page.content_path}
        )

    def item_guid(self, item):
        # pk-based, not URL-based: stable across page moves/renames so
        # readers don't re-surface every item when the URL changes.
        return f"flp-wiki:revision:{item.pk}"

    item_guid_is_permalink = False

    def item_pubdate(self, item):
        return item.created_at

    def item_updateddate(self, item):
        return item.created_at

    def item_author_name(self, item):
        return display_name(item.created_by) if item.created_by else ""
