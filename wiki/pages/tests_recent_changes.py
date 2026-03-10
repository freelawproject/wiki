"""Tests for the recent changes / user contributions view."""

import pytest
from django.urls import reverse

from wiki.pages.models import Page, PageRevision


@pytest.fixture
def staff_user(db):
    from django.contrib.auth.models import User

    from wiki.users.models import UserProfile

    u = User.objects.create_user(
        username="staff@free.law",
        email="staff@free.law",
        password="testpass",
        is_staff=True,
    )
    UserProfile.objects.create(user=u, display_name="Staff User")
    return u


@pytest.fixture
def non_staff_user(db):
    from django.contrib.auth.models import User

    from wiki.users.models import UserProfile

    u = User.objects.create_user(
        username="visitor@free.law",
        email="visitor@free.law",
        password="testpass",
        is_staff=False,
    )
    UserProfile.objects.create(user=u, display_name="Visitor")
    return u


@pytest.fixture
def pages_with_revisions(staff_user, non_staff_user):
    """Create pages with revisions from different users."""
    page1 = Page.objects.create(
        title="Alpha Page",
        slug="alpha",
        content="Alpha content",
        owner=staff_user,
        created_by=staff_user,
        updated_by=staff_user,
    )
    PageRevision.objects.create(
        page=page1,
        title=page1.title,
        content=page1.content,
        change_message="Created alpha",
        revision_number=1,
        created_by=staff_user,
    )

    page2 = Page.objects.create(
        title="Beta Page",
        slug="beta",
        content="Beta content",
        owner=non_staff_user,
        created_by=non_staff_user,
        updated_by=non_staff_user,
    )
    PageRevision.objects.create(
        page=page2,
        title=page2.title,
        content=page2.content,
        change_message="Created beta",
        revision_number=1,
        created_by=non_staff_user,
    )

    return page1, page2


@pytest.mark.django_db
class TestRecentChanges:
    def test_anonymous_redirected_to_login(self, client):
        url = reverse("recent_changes")
        resp = client.get(url)
        assert resp.status_code == 302
        assert "/u/login/" in resp.url

    def test_non_staff_gets_404(self, client, non_staff_user):
        client.force_login(non_staff_user)
        url = reverse("recent_changes")
        resp = client.get(url)
        assert resp.status_code == 404

    def test_staff_sees_recent_changes(
        self, client, staff_user, pages_with_revisions
    ):
        client.force_login(staff_user)
        url = reverse("recent_changes")
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"Alpha Page" in resp.content
        assert b"Beta Page" in resp.content

    def test_filter_by_user_url(
        self, client, staff_user, non_staff_user, pages_with_revisions
    ):
        client.force_login(staff_user)
        url = reverse(
            "recent_changes_user", kwargs={"username": "visitor"}
        )
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"Beta Page" in resp.content
        assert b"Alpha Page" not in resp.content

    def test_filter_by_user_query_param(
        self, client, staff_user, non_staff_user, pages_with_revisions
    ):
        client.force_login(staff_user)
        url = reverse("recent_changes") + "?user=visitor"
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"Beta Page" in resp.content
        assert b"Alpha Page" not in resp.content

    def test_filter_nonexistent_user_returns_404(self, client, staff_user):
        client.force_login(staff_user)
        url = reverse(
            "recent_changes_user",
            kwargs={"username": "nobody"},
        )
        resp = client.get(url)
        assert resp.status_code == 404

    def test_private_pages_excluded(self, client, staff_user, non_staff_user):
        """Staff can see all pages they have access to, but private pages
        owned by others are excluded."""
        private_page = Page.objects.create(
            title="Secret Page",
            slug="secret",
            content="Secret",
            owner=non_staff_user,
            created_by=non_staff_user,
            updated_by=non_staff_user,
            visibility=Page.Visibility.PRIVATE,
        )
        PageRevision.objects.create(
            page=private_page,
            title=private_page.title,
            content=private_page.content,
            change_message="Created secret",
            revision_number=1,
            created_by=non_staff_user,
        )

        client.force_login(staff_user)
        url = reverse("recent_changes")
        resp = client.get(url)
        assert resp.status_code == 200
        # Staff user is not the owner and has no explicit permission
        assert b"Secret Page" not in resp.content

    def test_heading_shows_contributions_when_filtered(
        self, client, staff_user, non_staff_user, pages_with_revisions
    ):
        client.force_login(staff_user)
        url = reverse(
            "recent_changes_user", kwargs={"username": "visitor"}
        )
        resp = client.get(url)
        assert b"Contributions by" in resp.content
        assert b"Visitor" in resp.content
