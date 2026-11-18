"""Tests for writing through the JSON API."""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from wiki.api import auth
from wiki.lib.models import EditLock
from wiki.pages.models import Page, PageRevision, SlugRedirect


@pytest.fixture
def tokens(monkeypatch):
    """Stand in for CourtListener: bearer tokens mapped to the email behind
    them."""
    known = {}
    monkeypatch.setattr(
        auth,
        "cached_verified_email_for",
        lambda token, request: known.get(token),
    )
    return known


@pytest.fixture
def writer(tokens, owner_user):
    """A token for the page's owner. The owner is also the system owner, so
    an account a test token mints never becomes it."""
    tokens["w"] = owner_user.email
    return "w"


def detail_url(page):
    return reverse("api_page_detail", kwargs={"path": page.content_path})


def patch(client, page, body, token="w"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.patch(
        detail_url(page),
        body,
        content_type="application/json",
        headers=headers,
    )


def create(client, body, token="w"):
    return client.post(
        reverse("api_page_list"),
        body,
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


class TestDetail:
    def test_carries_the_revision_and_whether_you_can_edit(
        self, client, page, writer
    ):
        anonymous = client.get(detail_url(page)).json()
        assert (anonymous["revision"], anonymous["can_edit"]) == (1, False)
        mine = client.get(
            detail_url(page), headers={"Authorization": "Bearer w"}
        ).json()
        assert (mine["revision"], mine["can_edit"]) == (1, True)


class TestEdit:
    def test_an_edit_makes_a_revision(self, page, writer, user):
        # CSRF checks on: a bearer-token write doesn't need a CSRF token.
        client = Client(enforce_csrf_checks=True)
        r = patch(
            client,
            page,
            {
                "base_revision": 1,
                "change_message": "Say hi",
                "content": "## Welcome\n\nHi, world.",
            },
        )
        assert r.status_code == 200, r.json()
        assert r.json()["revision"] == 2
        assert r.json()["content"] == "## Welcome\n\nHi, world."
        rev = PageRevision.objects.get(page=page, revision_number=2)
        assert (rev.created_by, rev.change_message) == (user, "Say hi")
        page.refresh_from_db()
        assert (page.updated_by, page.content) == (user, rev.content)

    def test_full_content_and_a_new_title_move_the_page(
        self, client, page, writer
    ):
        r = patch(
            client,
            page,
            {
                "base_revision": 1,
                "change_message": "Rename",
                "title": "First Steps",
                "content": "New text.",
            },
        )
        assert r.status_code == 200, r.json()
        assert (r.json()["path"], r.json()["content"]) == (
            "first-steps",
            "New text.",
        )
        assert SlugRedirect.objects.filter(old_slug="getting-started").exists()

    def test_a_stale_revision_is_a_conflict(self, client, page, writer):
        page.content = "Changed meanwhile."
        page.save()
        page.create_revision(page.owner, "Meanwhile")
        r = patch(
            client,
            page,
            {"base_revision": 1, "change_message": "x", "content": "Mine."},
        )
        assert r.status_code == 409
        assert r.json() == {
            "error": "conflict",
            "revision": 2,
            "detail": "The page has changed since that revision; read it again.",
        }
        page.refresh_from_db()
        assert page.content == "Changed meanwhile."

    def test_a_page_locked_in_the_editor_is_refused(
        self, client, page, writer, other_user
    ):
        EditLock.objects.create(
            page=page,
            user=other_user,
            expires_at=timezone.now() + EditLock.LOCK_DURATION,
        )
        r = patch(
            client,
            page,
            {"base_revision": 1, "change_message": "x", "content": "Mine."},
        )
        assert r.status_code == 409
        assert (r.json()["error"], r.json()["locked_by"]) == ("locked", "Bob")

    @pytest.mark.parametrize(
        "body, detail",
        [
            ({"change_message": "x", "content": "y"}, "`base_revision`"),
            ({"base_revision": 1, "content": "y"}, "`change_message`"),
            ({"base_revision": 1, "change_message": "x"}, "Nothing to change"),
            (
                {
                    "base_revision": 1,
                    "change_message": "x",
                    "title": "Getting Started",
                    "content": "## Welcome\n\nHello world.",
                },
                "already has that title",
            ),
        ],
    )
    def test_bad_requests(self, client, page, writer, body, detail):
        r = patch(client, page, body)
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_request"
        assert detail in r.json()["detail"]

    def test_a_session_alone_cannot_write(self, client, page, user):
        client.force_login(user)
        body = {"base_revision": 1, "change_message": "x", "content": "y"}
        r = patch(client, page, body, token=None)
        assert r.status_code == 401
        assert r["WWW-Authenticate"] == 'Bearer scope="openid wiki email"'

    def test_an_account_that_cannot_edit_the_page_is_refused(
        self, client, page, writer, tokens, other_user
    ):
        tokens["b"] = other_user.email
        body = {"base_revision": 1, "change_message": "x", "content": "y"}
        r = patch(client, page, body, token="b")
        assert r.status_code == 403
        assert r.json()["error"] == "forbidden"

    def test_an_anonymous_token_cannot_write(self, client, page, tokens):
        tokens["a"] = "someone@gmail.com"
        body = {"base_revision": 1, "change_message": "x", "content": "y"}
        r = patch(client, page, body, token="a")
        assert (r.status_code, r.json()["error"]) == (403, "forbidden")
        assert "WWW-Authenticate" not in r

    def test_a_token_missing_scopes_gets_a_challenge(
        self, client, page, tokens
    ):
        tokens["s"] = auth.MISSING_SCOPES
        body = {"base_revision": 1, "change_message": "x", "content": "y"}
        r = patch(client, page, body, token="s")
        assert (r.status_code, r.json()["error"]) == (
            403,
            "insufficient_scope",
        )
        assert r["WWW-Authenticate"] == (
            'Bearer error="insufficient_scope", scope="openid wiki email"'
        )


class TestCreate:
    def test_creates_a_page_that_inherits_its_directory(
        self, client, sub_directory, writer, user
    ):
        r = create(
            client,
            {
                "directory": "engineering",
                "title": "Deploys",
                "content": "How we deploy.",
                "change_message": "Add deploy notes",
            },
        )
        assert r.status_code == 201, r.json()
        assert (r.json()["path"], r.json()["revision"]) == (
            "engineering/deploys",
            1,
        )
        page = Page.objects.get(slug="deploys")
        assert (page.owner, page.directory) == (user, sub_directory)
        assert page.visibility == Page.Visibility.INHERIT
        assert page.revisions.get().change_message == "Add deploy notes"

    def test_an_unknown_directory_is_not_found(
        self, client, root_directory, writer
    ):
        body = {
            "directory": "nowhere",
            "title": "T",
            "content": "",
            "change_message": "x",
        }
        assert create(client, body).status_code == 404
        # The top level can't be named: a page there would start out public.
        assert create(client, {**body, "directory": "/"}).status_code == 400

    def test_a_directory_you_cannot_edit_is_refused(
        self, client, sub_directory, writer, tokens, other_user
    ):
        tokens["b"] = other_user.email
        body = {
            "directory": "engineering",
            "title": "T",
            "content": "",
            "change_message": "x",
        }
        r = create(client, body, token="b")
        assert r.status_code == 403
        assert not Page.objects.filter(slug="t").exists()
