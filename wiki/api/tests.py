"""Tests for the JSON API endpoints."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from wiki.api import auth
from wiki.pages.models import Page, PagePermission
from wiki.users.models import AllowedEmail


@pytest.fixture
def internal_page(owner_user):
    """An internal page; its owner is the system owner, so an account the
    API mints is never the first one and never becomes owner itself."""
    return Page.objects.create(
        title="Staff Only",
        slug="staff-only",
        content="The secret handshake.",
        owner=owner_user,
        created_by=owner_user,
        updated_by=owner_user,
        visibility=Page.Visibility.INTERNAL,
    )


@pytest.fixture
def identify(monkeypatch):
    """Stand in for CourtListener: a map of bearer tokens to emails."""
    tokens = {}
    monkeypatch.setattr(auth, "courtlistener_email", tokens.get)
    return tokens


def paths(client, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.get(reverse("api_page_list"), headers=headers)
    assert r.status_code == 200
    return [p["path"] for p in r.json()["pages"]]


class TestPageList:
    def test_anonymous_sees_public_only(self, client, page, internal_page):
        assert paths(client) == [page.content_path]

    def test_staff_sees_internal(self, client, page, internal_page, identify):
        identify["t"] = "new@free.law"
        assert paths(client, "t") == [page.content_path, "staff-only"]

    def test_guest_sees_only_what_is_granted(
        self, client, other_user, page, internal_page, identify
    ):
        guest = User.objects.create_user(
            "g@contractor.test", "g@contractor.test"
        )
        AllowedEmail.objects.create(email=guest.email)
        private = Page.objects.create(
            title="Vendor Contract",
            slug="vendor-contract",
            content="Terms.",
            owner=other_user,
            created_by=other_user,
            updated_by=other_user,
            visibility=Page.Visibility.PRIVATE,
        )
        PagePermission.objects.create(page=private, user=guest)
        identify["t"] = guest.email
        assert paths(client, "t") == [page.content_path, "vendor-contract"]


def make_pages(owner, titles):
    for title in titles:
        Page.objects.create(
            title=title,
            slug=title.lower(),
            content="Chapter text.",
            owner=owner,
            created_by=owner,
            updated_by=owner,
        )


@pytest.mark.parametrize(
    "url_name, query, key, setting",
    [
        ("api_page_list", {}, "pages", "PAGE_LIST_RESULTS_PER_PAGE"),
        ("api_search", {"q": "chapter"}, "results", "SEARCH_RESULTS_PER_PAGE"),
    ],
)
def test_pagination(
    client, owner_user, settings, url_name, query, key, setting
):
    setattr(settings, setting, 2)
    make_pages(owner_user, ["Alpha", "Beta", "Gamma"])
    first = client.get(reverse(url_name), query).json()
    assert (first["total"], first["page"], first["next_page"]) == (3, 1, 2)
    assert len(first[key]) == 2
    last = client.get(reverse(url_name), {**query, "page": 2}).json()
    assert (last["page"], last["next_page"]) == (2, None)
    assert len(last[key]) == 1
    assert {p["path"] for p in first[key] + last[key]} == {
        "alpha",
        "beta",
        "gamma",
    }
    # A page number that isn't one at all still answers with the first page.
    assert (
        client.get(reverse(url_name), {**query, "page": "x"}).json()["page"]
        == 1
    )


class TestSearchAndDetail:
    def test_search(self, client, page, internal_page, identify):
        identify["t"] = "new@free.law"
        r = client.get(
            reverse("api_search"),
            {"q": "secret"},
            headers={"Authorization": "Bearer t"},
        )
        assert r.json()["total"] == 1
        result = r.json()["results"][0]
        assert result["path"] == "staff-only"
        assert "secret" in result["snippet"]
        assert "<mark>" not in result["snippet"]
        anonymous = client.get(reverse("api_search"), {"q": "secret"})
        assert anonymous.json()["total"] == 0

    def test_detail_hides_what_cannot_be_viewed(
        self, client, page, internal_page
    ):
        r = client.get(
            reverse("api_page_detail", kwargs={"path": page.content_path})
        )
        assert r.json()["content"] == page.content
        r = client.get(
            reverse("api_page_detail", kwargs={"path": "staff-only"})
        )
        assert r.status_code == 404
