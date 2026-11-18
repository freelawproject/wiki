"""Tests for writing through the JSON API."""

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from wiki.api import auth, views
from wiki.lib.models import EditLock
from wiki.lib.page_saves import current_revision_number
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


class TestDetailRevision:
    def test_content_is_never_older_than_its_revision(
        self, client, page, monkeypatch
    ):
        # An edit that commits between reading the revision number and the
        # content shows up in the content, so an edit based on that content
        # is refused as a conflict rather than overwriting it.
        def then_someone_edits(p):
            number = current_revision_number(p)
            Page.objects.filter(pk=p.pk).update(content="Newer.")
            return number

        monkeypatch.setattr(
            views, "current_revision_number", then_someone_edits
        )
        body = client.get(detail_url(page) + "?raw=true").json()
        assert (body["revision"], body["content"]) == (1, "Newer.")


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

    def test_an_api_edit_leaves_editor_locks_alone(
        self, client, page, writer, other_user, monkeypatch
    ):
        # A lock taken after the API's check (simulated by skipping the
        # check) belongs to an open editor, which the API mustn't release.
        EditLock.objects.create(
            page=page,
            user=other_user,
            expires_at=timezone.now() + EditLock.LOCK_DURATION,
        )
        monkeypatch.setattr(
            views, "get_active_lock_for_page", lambda page: None
        )
        r = patch(
            client,
            page,
            {"base_revision": 1, "change_message": "x", "content": "Mine."},
        )
        assert r.status_code == 200
        assert EditLock.objects.filter(page=page).exists()

    def test_content_that_saves_unchanged_is_no_change(
        self, client, page, writer
    ):
        Page.objects.filter(pk=page.pk).update(content="    Hello")
        r = patch(
            client,
            page,
            {"base_revision": 1, "change_message": "x", "content": "\tHello"},
        )
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")
        assert page.revisions.count() == 1

    def test_your_own_open_editor_blocks_an_edit(
        self, client, page, writer, user
    ):
        # Saving the editor's form afterwards would overwrite the API edit.
        EditLock.objects.create(
            page=page,
            user=user,
            expires_at=timezone.now() + EditLock.LOCK_DURATION,
        )
        r = patch(
            client,
            page,
            {"base_revision": 1, "change_message": "x", "content": "Mine."},
        )
        assert (r.status_code, r.json()["error"]) == (409, "locked")
        assert "You have this page open" in r.json()["detail"]
        page.refresh_from_db()
        assert page.content != "Mine."

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

    @pytest.mark.parametrize("text", ["a\x00b", "a\ud800b"])
    @pytest.mark.parametrize("field", ["content", "title", "change_message"])
    def test_text_postgres_cannot_store_is_a_bad_request(
        self, client, page, writer, field, text
    ):
        body = {"base_revision": 1, "change_message": "x", "content": "y"}
        r = patch(client, page, {**body, field: text})
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")

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

    def test_a_page_you_cannot_see_yet_still_gets_the_challenge(
        self, client, private_page, tokens
    ):
        # The token is checked before the page is looked up, so a client
        # gets the challenge it can act on rather than a 404.
        body = {"base_revision": 1, "change_message": "x", "content": "y"}
        r = patch(client, private_page, body, token=None)
        assert r.status_code == 401
        assert r["WWW-Authenticate"] == 'Bearer scope="openid wiki email"'
        tokens["s"] = auth.MISSING_SCOPES
        r = patch(client, private_page, body, token="s")
        assert (r.status_code, r.json()["error"]) == (
            403,
            "insufficient_scope",
        )


class TestDataSource:
    URL = "https://www.courtlistener.com/api/rest/v4/wiki-data/"

    @pytest.fixture(autouse=True)
    def _allowlist(self, settings):
        settings.DATA_SOURCE_ALLOWED_DOMAINS = ["www.courtlistener.com"]

    def test_an_editor_sees_the_data_source(self, client, page, writer):
        Page.objects.filter(pk=page.pk).update(
            data_source_url=self.URL, data_source_ttl=600
        )
        mine = client.get(
            detail_url(page), headers={"Authorization": "Bearer w"}
        ).json()
        assert (mine["data_source_url"], mine["data_source_ttl"]) == (
            self.URL,
            600,
        )
        anonymous = client.get(detail_url(page)).json()
        assert "data_source_url" not in anonymous

    def test_an_edit_sets_and_removes_the_data_source(
        self, client, page, writer
    ):
        r = patch(
            client,
            page,
            {
                "base_revision": 1,
                "change_message": "Add data",
                "data_source_url": self.URL,
                "data_source_ttl": 900,
            },
        )
        assert r.status_code == 200, r.json()
        page.refresh_from_db()
        assert (page.data_source_url, page.data_source_ttl) == (self.URL, 900)
        assert page.content == "## Welcome\n\nHello world."

        r = patch(
            client,
            page,
            {"base_revision": 2, "change_message": "x", "data_source_url": ""},
        )
        assert r.status_code == 200, r.json()
        page.refresh_from_db()
        assert (page.data_source_url, page.data_source_ttl) == ("", 900)

    @pytest.mark.parametrize("ttl", [10, 86400])
    def test_the_cache_time_bounds_are_allowed(
        self, client, page, writer, ttl
    ):
        body = {"base_revision": 1, "change_message": "x"}
        r = patch(client, page, {**body, "data_source_ttl": ttl})
        assert r.status_code == 200, r.json()
        assert r.json()["data_source_ttl"] == ttl

    def test_null_removes_the_data_source(self, client, page, writer):
        Page.objects.filter(pk=page.pk).update(data_source_url=self.URL)
        r = patch(
            client,
            page,
            {
                "base_revision": 1,
                "change_message": "x",
                "data_source_url": None,
            },
        )
        assert r.status_code == 200, r.json()
        page.refresh_from_db()
        assert page.data_source_url == ""

    def test_the_same_data_source_is_no_change(self, client, page, writer):
        Page.objects.filter(pk=page.pk).update(data_source_url=self.URL)
        r = patch(
            client,
            page,
            {
                "base_revision": 1,
                "change_message": "x",
                "data_source_url": self.URL,
            },
        )
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")

    def test_a_create_sets_the_data_source(
        self, client, sub_directory, writer
    ):
        r = create(
            client,
            {
                "directory": "engineering",
                "title": "Stats",
                "content": "We have [[ total ]] cases.",
                "change_message": "x",
                "data_source_url": self.URL,
            },
        )
        assert r.status_code == 201, r.json()
        assert (r.json()["data_source_url"], r.json()["data_source_ttl"]) == (
            self.URL,
            300,
        )

    def test_a_create_with_a_disallowed_source_is_refused(
        self, client, sub_directory, writer
    ):
        r = create(
            client,
            {
                "directory": "engineering",
                "title": "Stats",
                "content": "",
                "change_message": "x",
                "data_source_url": "https://evil.example/x.json",
            },
        )
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")
        assert not Page.objects.filter(slug="stats").exists()

    @pytest.mark.parametrize(
        "fields, detail",
        [
            ({"data_source_url": "https://evil.example/x.json"}, "domain"),
            ({"data_source_url": "not a url"}, "valid URL"),
            ({"data_source_url": 5}, "must be a string"),
            ({"data_source_ttl": 9}, "between 10 and 86400"),
            ({"data_source_ttl": 86401}, "between 10 and 86400"),
            # Past a 32-bit integer: refused, not a database error.
            ({"data_source_ttl": 2**31}, "between 10 and 86400"),
            ({"data_source_ttl": "300"}, "whole number"),
            ({"data_source_ttl": True}, "whole number"),
        ],
    )
    def test_bad_data_sources_are_refused(
        self, client, page, writer, fields, detail
    ):
        body = {"base_revision": 1, "change_message": "x", **fields}
        r = patch(client, page, body)
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")
        assert detail in r.json()["detail"]
        page.refresh_from_db()
        assert page.data_source_url == ""


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


class TestWriteRateLimits:
    @pytest.fixture(autouse=True)
    def _clear_cache(self, db):
        cache.clear()
        yield
        cache.clear()

    @staticmethod
    def _create(client, n, token="w"):
        return create(
            client,
            {
                "directory": "engineering",
                "title": f"Page {n}",
                "content": "",
                "change_message": "x",
            },
            token=token,
        )

    @override_settings(RATELIMIT_ENABLE=True)
    def test_api_writes_skip_the_sitewide_cap(
        self, client, sub_directory, writer
    ):
        # Every MCP user writes from the MCP server's address, so the
        # sitewide per-address cap (10 a minute) mustn't apply.
        for n in range(15):
            assert self._create(client, n).status_code == 201

    @override_settings(RATELIMIT_ENABLE=True)
    def test_an_accounts_tokens_share_one_budget(
        self, client, sub_directory, writer, tokens, owner_user
    ):
        tokens["w2"] = owner_user.email
        for n in range(30):
            token = "w" if n % 2 else "w2"
            assert self._create(client, n, token).status_code == 201
        r = self._create(client, 30, "w2")
        assert (r.status_code, r.json()["error"]) == (429, "ratelimited")
