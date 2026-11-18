"""Tests for previewing page source through the JSON API."""

import pytest
from django.urls import reverse

from wiki.api import auth
from wiki.lib import data_source


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
def member(tokens, user):
    """A token for a wiki account."""
    tokens["m"] = user.email
    return "m"


def preview(client, body, token="m"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        reverse("api_preview"),
        body,
        content_type="application/json",
        headers=headers,
    )


class TestPreview:
    def test_renders_markdown_without_saving(self, client, member):
        r = preview(client, {"content": "# Hello\n\nSome **bold** text."})
        assert r.status_code == 200, r.json()
        assert '<h1 id="hello">Hello</h1>' in r.json()["html"]
        assert "<strong>bold</strong>" in r.json()["html"]

    def test_fills_placeholders_from_a_fresh_fetch(
        self, client, member, settings, monkeypatch
    ):
        settings.DATA_SOURCE_ALLOWED_DOMAINS = ["www.courtlistener.com"]
        fetched = []

        def fetch(url):
            fetched.append(url)
            return {"stats": {"open": 42}}

        monkeypatch.setattr(data_source, "fetch_data", fetch)
        monkeypatch.setattr(
            data_source,
            "fetch_page_data",
            lambda url, ttl: pytest.fail("previews skip the cache"),
        )
        url = "https://www.courtlistener.com/api/rest/v4/wiki-data/"
        body = {"content": "Open: [[ stats.open ]]", "data_source_url": url}
        r = preview(client, body)
        assert r.status_code == 200, r.json()
        assert "Open: 42" in r.json()["html"]
        assert fetched == [url]

    def test_renders_as_the_caller(
        self, client, owner_user, private_page, member, tokens, other_user
    ):
        # A link to a page only its owner can see resolves for the owner.
        # (Naming a system owner stops every account being treated as one.)
        tokens["x"] = other_user.email
        body = {"content": "[notes](#secret-notes)"}
        link = 'href="/c/secret-notes"'
        assert link in preview(client, body).json()["html"]
        assert link not in preview(client, body, token="x").json()["html"]

    @pytest.mark.parametrize("token, status", [(None, 401), ("stranger", 403)])
    def test_needs_a_wiki_account(
        self, client, db, settings, monkeypatch, tokens, token, status
    ):
        # Not even a data source is fetched for a caller who couldn't sign
        # in to the wiki.
        settings.DATA_SOURCE_ALLOWED_DOMAINS = []
        tokens["stranger"] = "stranger@nowhere.example"
        fetched = []
        monkeypatch.setattr(
            data_source, "fetch_data", lambda url: fetched.append(url) or {}
        )
        body = {"content": "x", "data_source_url": "http://127.0.0.1:8000/"}
        assert preview(client, body, token=token).status_code == status
        assert fetched == []

    @pytest.mark.parametrize(
        "body, detail",
        [
            ({}, "`content` is required"),
            (
                {"content": "x", "data_source_url": "https://evil.example/"},
                "domain",
            ),
        ],
    )
    def test_bad_requests(self, client, member, settings, body, detail):
        settings.DATA_SOURCE_ALLOWED_DOMAINS = ["www.courtlistener.com"]
        r = preview(client, body)
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")
        assert detail in r.json()["detail"]

    def test_only_accepts_post(self, client, db):
        assert client.get(reverse("api_preview")).status_code == 405
