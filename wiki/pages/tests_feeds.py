"""Tests for the per-page revision feed at <path>.rss (Atom payload)."""

import pytest
from django.urls import reverse

from wiki.pages.feeds import FEED_ITEM_LIMIT
from wiki.pages.models import PageRevision


def _feed_url(page):
    return reverse("page_feed", kwargs={"path": page.content_path})


@pytest.fixture
def public_history_page(page):
    page.history_is_public = True
    page.save(update_fields=["history_is_public"])
    return page


def _add_revision(page, user, n, message="edit"):
    return PageRevision.objects.create(
        page=page,
        title=page.title,
        content=f"content v{n}",
        change_message=message,
        revision_number=n,
        created_by=user,
    )


class TestFeedAccess:
    def test_anonymous_gets_atom_feed(self, client, public_history_page):
        r = client.get(_feed_url(public_history_page))
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("application/atom+xml")

    def test_anonymous_404_when_history_not_public(self, client, page):
        r = client.get(_feed_url(page))
        assert r.status_code == 404

    def test_anonymous_404_when_page_private(self, client, private_page):
        private_page.history_is_public = True
        private_page.save(update_fields=["history_is_public"])
        r = client.get(_feed_url(private_page))
        assert r.status_code == 404

    def test_missing_page_404(self, client, db):
        r = client.get(
            reverse("page_feed", kwargs={"path": "no-such-page"})
        )
        assert r.status_code == 404

    def test_authenticated_can_fetch_private_history_feed(
        self, client, user, page
    ):
        client.force_login(user)
        r = client.get(_feed_url(page))
        assert r.status_code == 200

    def test_soft_deleted_page_404(self, client, public_history_page, user):
        public_history_page.is_deleted = True
        public_history_page.deleted_by = user
        public_history_page.save()
        r = client.get(_feed_url(public_history_page))
        assert r.status_code == 404


class TestFeedContent:
    def test_entries_newest_first_with_diff_links(
        self, client, user, public_history_page
    ):
        _add_revision(public_history_page, user, 2, "second change")
        _add_revision(public_history_page, user, 3, "third change")
        r = client.get(_feed_url(public_history_page))
        content = r.content.decode()

        assert "Revision 3: third change" in content
        assert content.index("Revision 3") < content.index("Revision 2")
        diff_url = reverse(
            "page_diff",
            kwargs={
                "path": public_history_page.content_path,
                "v1": 2,
                "v2": 3,
            },
        )
        assert diff_url in content
        # Revision 1 links to history (nothing to diff against).
        history_url = reverse(
            "page_history",
            kwargs={"path": public_history_page.content_path},
        )
        assert history_url in content

    def test_guids_are_pk_based(self, client, user, public_history_page):
        rev = _add_revision(public_history_page, user, 2)
        r = client.get(_feed_url(public_history_page))
        assert f"flp-wiki:revision:{rev.pk}" in r.content.decode()

    def test_item_limit(self, client, user, public_history_page):
        for n in range(2, FEED_ITEM_LIMIT + 5):
            _add_revision(public_history_page, user, n)
        r = client.get(_feed_url(public_history_page))
        assert r.content.decode().count("<entry>") == FEED_ITEM_LIMIT

    def test_last_modified_header(self, client, public_history_page):
        r = client.get(_feed_url(public_history_page))
        assert "Last-Modified" in r.headers


class TestFeedCaching:
    def test_anonymous_response_is_cdn_cacheable(
        self, client, public_history_page
    ):
        r = client.get(_feed_url(public_history_page))
        assert (
            r.headers["Cache-Control"]
            == "public, max-age=30, s-maxage=2592000"
        )

    def test_authenticated_response_is_private(
        self, client, user, public_history_page
    ):
        client.force_login(user)
        r = client.get(_feed_url(public_history_page))
        assert r.headers["Cache-Control"] == "private, no-store"
