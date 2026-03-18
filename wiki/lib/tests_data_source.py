"""Tests for wiki.lib.data_source — fetching, caching, and substitution."""

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import pytest
from django.test import override_settings

from wiki.lib.data_source import (
    _cache,
    _cache_lock,
    clear_cache,
    fetch_page_data,
    is_domain_allowed,
    substitute_data_variables,
)


@pytest.fixture(autouse=True)
def _clear_data_source_cache():
    """Ensure each test starts with a clean in-memory cache."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture(autouse=True)
def _allow_localhost(settings):
    """Allow 127.0.0.1 in tests so the local test server works."""
    settings.DATA_SOURCE_ALLOWED_DOMAINS = ["127.0.0.1"]


# ── substitute_data_variables ─────────────────────────────────────────


class TestSubstituteDataVariables:
    def test_simple_replacement(self):
        content = "The count is [[ count ]]."
        data = {"count": "42"}
        assert substitute_data_variables(content, data) == "The count is 42."

    def test_nested_key(self):
        content = "Total: [[ stats.total ]]"
        data = {"stats": {"total": 100}}
        assert substitute_data_variables(content, data) == "Total: 100"

    def test_deeply_nested_key(self):
        content = "[[ a.b.c ]]"
        data = {"a": {"b": {"c": "deep"}}}
        assert substitute_data_variables(content, data) == "deep"

    def test_missing_key_left_as_is(self):
        content = "Value: [[ missing ]]"
        data = {"other": "x"}
        assert substitute_data_variables(content, data) == "Value: [[ missing ]]"

    def test_partial_nested_key_left_as_is(self):
        content = "[[ a.b.c ]]"
        data = {"a": {"b": "not_a_dict"}}
        assert substitute_data_variables(content, data) == "[[ a.b.c ]]"

    def test_none_value_left_as_is(self):
        content = "[[ key ]]"
        data = {"key": None}
        assert substitute_data_variables(content, data) == "[[ key ]]"

    def test_integer_value_converted_to_string(self):
        content = "[[ num ]]"
        data = {"num": 7}
        assert substitute_data_variables(content, data) == "7"

    def test_multiple_placeholders(self):
        content = "[[ a ]] and [[ b ]]"
        data = {"a": "1", "b": "2"}
        assert substitute_data_variables(content, data) == "1 and 2"

    def test_no_spaces_in_brackets(self):
        content = "[[compact]]"
        data = {"compact": "yes"}
        assert substitute_data_variables(content, data) == "yes"

    def test_extra_spaces_in_brackets(self):
        content = "[[   padded   ]]"
        data = {"padded": "yes"}
        assert substitute_data_variables(content, data) == "yes"

    def test_empty_data_returns_content_unchanged(self):
        content = "[[ key ]]"
        assert substitute_data_variables(content, {}) == "[[ key ]]"
        assert substitute_data_variables(content, None) == "[[ key ]]"

    def test_fenced_code_block_not_substituted(self):
        content = "```\n[[ key ]]\n```"
        data = {"key": "replaced"}
        assert substitute_data_variables(content, data) == content

    def test_inline_code_not_substituted(self):
        content = "Use `[[ key ]]` syntax"
        data = {"key": "replaced"}
        assert substitute_data_variables(content, data) == content

    def test_mixed_code_and_content(self):
        content = "[[ a ]] and `[[ b ]]` and [[ c ]]"
        data = {"a": "1", "b": "2", "c": "3"}
        result = substitute_data_variables(content, data)
        assert result == "1 and `[[ b ]]` and 3"


# ── fetch_page_data ──────────────────────────────────────────────────


def _make_test_server(response_data, status=200, delay=0):
    """Start a local HTTP server that returns JSON. Returns (url, server)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if delay:
                time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode())

        def log_message(self, format, *args):
            pass  # suppress logs

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}/data", server


@pytest.fixture()
def json_server():
    """Fixture that yields a factory for test HTTP servers."""
    servers = []

    def factory(data, **kwargs):
        url, server = _make_test_server(data, **kwargs)
        servers.append(server)
        return url

    yield factory
    for s in servers:
        s.shutdown()


@pytest.mark.django_db
class TestFetchPageData:
    def test_fetches_json(self, json_server):
        url = json_server({"foo": "bar"})
        data = fetch_page_data(url, ttl=60)
        assert data == {"foo": "bar"}

    def test_returns_cached_on_second_call(self, json_server):
        url = json_server({"n": 1})
        fetch_page_data(url, ttl=60)
        # Mutate the cache entry to prove we're reading from cache
        with _cache_lock:
            _cache[url]["data"]["n"] = 999
        second = fetch_page_data(url, ttl=60)
        assert second == {"n": 999}

    def test_stale_fallback_on_error(self, json_server):
        url = json_server({"val": "ok"})
        fetch_page_data(url, ttl=60)

        # Expire the cache to make it stale (but within 3x)
        with _cache_lock:
            _cache[url]["fetched_at"] -= 120  # 2 minutes old, ttl=60

        # Patch _do_fetch to simulate failure
        with patch(
            "wiki.lib.data_source._do_fetch", side_effect=Exception("down")
        ):
            data = fetch_page_data(url, ttl=60)
        assert data == {"val": "ok"}

    def test_expired_beyond_grace_returns_empty_on_error(self, json_server):
        url = json_server({"val": "ok"})
        fetch_page_data(url, ttl=60)

        # Expire beyond 3x TTL
        with _cache_lock:
            _cache[url]["fetched_at"] -= 300  # 5 minutes old, ttl=60

        with patch(
            "wiki.lib.data_source._do_fetch", side_effect=Exception("down")
        ):
            data = fetch_page_data(url, ttl=60)
        assert data == {}

    def test_fetch_failure_uncached_returns_empty(self):
        with patch(
            "wiki.lib.data_source._do_fetch", side_effect=Exception("fail")
        ):
            data = fetch_page_data("http://127.0.0.1:99999/x", ttl=60)
        assert data == {}

    def test_stale_refetch_updates_cache(self, json_server):
        url = json_server({"v": 1})
        fetch_page_data(url, ttl=60)

        # Make stale
        with _cache_lock:
            _cache[url]["fetched_at"] -= 120

        # Patch to return new data
        with patch(
            "wiki.lib.data_source._do_fetch", return_value={"v": 2}
        ):
            data = fetch_page_data(url, ttl=60)
        assert data == {"v": 2}
        # Cache should now be fresh
        with _cache_lock:
            assert _cache[url]["data"] == {"v": 2}


# ── Integration: model fields + rendering ─────────────────────────────


@pytest.mark.django_db
class TestPageDataSourceIntegration:
    def test_page_has_data_source_fields(self):
        from wiki.pages.models import Page

        page = Page(title="Test", content="Hello [[ name ]]")
        assert page.data_source_url == ""
        assert page.data_source_ttl == 300

    def test_render_with_data_source(self, client, json_server):
        from wiki.pages.models import Page

        url = json_server({"name": "World"})
        page = Page.objects.create(
            title="Data Test",
            content="Hello [[ name ]]!",
            data_source_url=url,
            data_source_ttl=60,
        )
        response = client.get(page.get_absolute_url())
        assert response.status_code == 200
        assert b"Hello World!" in response.content

    def test_render_without_data_source(self, client):
        from wiki.pages.models import Page

        page = Page.objects.create(
            title="Plain Page",
            content="Hello [[ name ]]!",
        )
        response = client.get(page.get_absolute_url())
        assert response.status_code == 200
        # Placeholder should remain (no data source configured)
        assert b"[[ name ]]" in response.content


# ── Domain allowlist ──────────────────────────────────────────────────


class TestDomainAllowlist:
    @override_settings(
        DATA_SOURCE_ALLOWED_DOMAINS=["www.courtlistener.com"]
    )
    def test_allowed_domain(self):
        assert is_domain_allowed("https://www.courtlistener.com/api/rest/v4/")

    @override_settings(
        DATA_SOURCE_ALLOWED_DOMAINS=["www.courtlistener.com"]
    )
    def test_disallowed_domain(self):
        assert not is_domain_allowed("https://evil.example.com/data")

    @override_settings(DATA_SOURCE_ALLOWED_DOMAINS=[])
    def test_empty_allowlist_permits_all(self):
        assert is_domain_allowed("https://anything.example.com/data")

    @override_settings(
        DATA_SOURCE_ALLOWED_DOMAINS=["a.example.com", "b.example.com"]
    )
    def test_multiple_domains(self):
        assert is_domain_allowed("https://a.example.com/x")
        assert is_domain_allowed("https://b.example.com/y")
        assert not is_domain_allowed("https://c.example.com/z")

    @override_settings(
        DATA_SOURCE_ALLOWED_DOMAINS=["www.courtlistener.com"]
    )
    def test_blocked_domain_returns_empty_dict(self):
        data = fetch_page_data("https://evil.example.com/data", ttl=60)
        assert data == {}
