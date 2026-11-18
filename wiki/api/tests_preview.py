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


def preview(client, body, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        reverse("api_preview"),
        body,
        content_type="application/json",
        headers=headers,
    )


class TestPreview:
    def test_renders_markdown_without_saving(self, client, db):
        r = preview(client, {"content": "# Hello\n\nSome **bold** text."})
        assert r.status_code == 200
        assert '<h1 id="hello">Hello</h1>' in r.json()["html"]
        assert "<strong>bold</strong>" in r.json()["html"]

    def test_fills_placeholders_from_the_data_source(
        self, client, db, settings, monkeypatch
    ):
        settings.DATA_SOURCE_ALLOWED_DOMAINS = ["www.courtlistener.com"]
        fetched = []

        def fetch(url, ttl):
            fetched.append((url, ttl))
            return {"stats": {"open": 42}}

        monkeypatch.setattr(data_source, "fetch_page_data", fetch)
        url = "https://www.courtlistener.com/api/rest/v4/wiki-data/"
        r = preview(
            client,
            {
                "content": "Open: [[ stats.open ]]",
                "data_source_url": url,
                "data_source_ttl": 600,
            },
        )
        assert r.status_code == 200, r.json()
        assert "Open: 42" in r.json()["html"]
        assert fetched == [(url, 600)]

    def test_renders_as_the_caller(self, client, private_page, tokens, user):
        # A link to a page only its owner can see resolves for the owner.
        tokens["o"] = user.email
        body = {"content": "[notes](#secret-notes)"}
        link = 'href="/c/secret-notes"'
        assert link not in preview(client, body).json()["html"]
        assert link in preview(client, body, token="o").json()["html"]

    @pytest.mark.parametrize(
        "body, detail",
        [
            ({}, "`content` is required"),
            (
                {"content": "x", "data_source_url": "https://evil.example/"},
                "domain",
            ),
            ({"content": "x", "data_source_ttl": 5}, "between 10 and 86400"),
        ],
    )
    def test_bad_requests(self, client, db, settings, body, detail):
        settings.DATA_SOURCE_ALLOWED_DOMAINS = ["www.courtlistener.com"]
        r = preview(client, body)
        assert (r.status_code, r.json()["error"]) == (400, "invalid_request")
        assert detail in r.json()["detail"]

    def test_only_accepts_post(self, client, db):
        assert client.get(reverse("api_preview")).status_code == 405
