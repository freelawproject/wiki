"""Tests for SEO infrastructure: descriptions, middleware, sitemaps, robots.txt."""

import json

import pytest
from django.test import RequestFactory

from wiki.directories.models import Directory
from wiki.lib.middleware import SEOHeadersMiddleware
from wiki.lib.seo import build_breadcrumbs_jsonld, extract_description
from wiki.pages.models import Page

# ── extract_description ──────────────────────────────────────────────


class TestExtractDescription:
    def test_plain_text(self):
        assert extract_description("Hello world") == "Hello world"

    def test_strips_headings(self):
        md = "# Title\n\nSome paragraph text here."
        result = extract_description(md)
        assert "Title" not in result
        assert "Some paragraph text here." in result

    def test_strips_code_blocks(self):
        md = "Intro text.\n\n```python\nprint('hi')\n```\n\nAfter code."
        result = extract_description(md)
        assert "print" not in result
        assert "Intro text." in result

    def test_converts_links_to_text(self):
        md = "See [this page](https://example.com) for details."
        result = extract_description(md)
        assert "this page" in result
        assert "https://example.com" not in result

    def test_strips_bold_italic(self):
        md = "This is **bold** and *italic* text."
        result = extract_description(md)
        assert "**" not in result
        assert "*" not in result
        assert "bold" in result

    def test_strips_images(self):
        md = "Text before ![alt text](image.png) and after."
        result = extract_description(md)
        assert "alt text" not in result
        assert "image.png" not in result
        assert "Text before" in result

    def test_truncates_to_max_length(self):
        md = "A " * 200
        result = extract_description(md, max_length=50)
        assert len(result) <= 53  # 50 + "..."
        assert result.endswith("...")

    def test_empty_input(self):
        assert extract_description("") == ""
        assert extract_description(None) == ""

    def test_strips_html_tags(self):
        md = "Hello <strong>world</strong> text."
        result = extract_description(md)
        assert "<strong>" not in result
        assert "world" in result

    def test_strips_blockquotes(self):
        md = "> Quoted text\n\nNormal text."
        result = extract_description(md)
        assert "Quoted text" in result


# ── build_breadcrumbs_jsonld ─────────────────────────────────────────


class TestBreadcrumbsJsonLd:
    def test_basic_breadcrumbs(self):
        crumbs = [("Home", "/c/"), ("Engineering", "/c/engineering")]
        result = json.loads(
            build_breadcrumbs_jsonld(crumbs, "https://wiki.free.law")
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "BreadcrumbList"
        assert len(result["itemListElement"]) == 2
        assert result["itemListElement"][0]["position"] == 1
        assert result["itemListElement"][0]["name"] == "Home"
        assert (
            result["itemListElement"][0]["item"] == "https://wiki.free.law/c/"
        )
        assert result["itemListElement"][1]["position"] == 2

    def test_absolute_urls_preserved(self):
        crumbs = [("Home", "https://wiki.free.law/c/")]
        result = json.loads(
            build_breadcrumbs_jsonld(crumbs, "https://wiki.free.law")
        )
        assert (
            result["itemListElement"][0]["item"] == "https://wiki.free.law/c/"
        )


# ── SEOHeadersMiddleware ─────────────────────────────────────────────


class TestSEOHeadersMiddleware:
    def _make_middleware(self, response_fn):
        return SEOHeadersMiddleware(response_fn)

    def _make_request(self, path="/c/some-page"):
        factory = RequestFactory()
        return factory.get(path)

    def test_noindex_on_admin_path(self):
        from django.http import HttpResponse

        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/admin/")
        response = middleware(request)
        assert response["X-Robots-Tag"] == "noindex, nofollow"

    def test_noindex_on_api_path(self):
        from django.http import HttpResponse

        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/api/something")
        response = middleware(request)
        assert response["X-Robots-Tag"] == "noindex, nofollow"

    def test_noindex_when_view_sets_flag(self):
        from django.http import HttpResponse

        def get_response(request):
            request.seo_noindex = True
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/c/private-page")
        response = middleware(request)
        assert response["X-Robots-Tag"] == "noindex, nofollow"

    def test_no_noindex_on_public_content(self):
        from django.http import HttpResponse

        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/c/public-page")
        response = middleware(request)
        assert "X-Robots-Tag" not in response

    def test_canonical_header(self):
        from django.http import HttpResponse

        def get_response(request):
            request.seo_canonical = "https://wiki.free.law/c/my-page"
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/c/my-page")
        response = middleware(request)
        assert (
            response["Link"]
            == '<https://wiki.free.law/c/my-page>; rel="canonical"'
        )

    def test_noindex_prefixes(self):
        """All non-content prefixes should get noindex."""
        from django.http import HttpResponse

        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        for prefix in [
            "/admin/",
            "/api/",
            "/u/",
            "/search/",
            "/files/",
            "/unsubscribe/",
        ]:
            request = self._make_request(prefix)
            response = middleware(request)
            assert response["X-Robots-Tag"] == "noindex, nofollow", (
                f"Missing noindex for {prefix}"
            )


# ── Robots.txt ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRobotsTxt:
    def test_robots_txt_content(self, client):
        response = client.get("/robots.txt")
        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain"
        content = response.content.decode()
        assert "User-agent: *" in content
        assert "Allow: /c/" in content
        assert "Disallow: /admin/" in content
        assert "Disallow: /api/" in content
        assert "Disallow: /u/" in content
        assert "Disallow: /search/" in content
        assert "Disallow: /files/" in content
        assert "Disallow: /unsubscribe/" in content
        assert "Sitemap:" in content


# ── Sitemap ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSitemap:
    def test_sitemap_includes_public_page(self, client, user):
        Page.objects.create(
            title="Public Page",
            slug="public-page",
            content="Hello",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        response = client.get("/sitemap.xml")
        assert response.status_code == 200
        content = response.content.decode()
        assert "/c/public-page" in content

    def test_sitemap_excludes_private_page(self, client, user):
        Page.objects.create(
            title="Private Page",
            slug="private-page",
            content="Secret",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "private-page" not in content

    def test_sitemap_includes_public_directory(self, client):
        Directory.objects.create(
            path="",
            title="Home",
            visibility=Directory.Visibility.PUBLIC,
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "/c/" in content

    def test_sitemap_excludes_private_directory(self, client):
        Directory.objects.create(
            path="secret",
            title="Secret",
            visibility=Directory.Visibility.PRIVATE,
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "/c/secret" not in content


# ── Meta tags in HTML responses ──────────────────────────────────────


@pytest.mark.django_db
class TestPageMetaTags:
    def test_public_page_has_og_tags(self, client, page, owner_user):
        client.force_login(owner_user)
        response = client.get(page.get_absolute_url())
        content = response.content.decode()
        assert "og:title" in content
        assert "og:description" in content
        assert "og:type" in content
        assert "twitter:card" in content

    def test_public_page_has_canonical(self, client, page, owner_user):
        client.force_login(owner_user)
        response = client.get(page.get_absolute_url())
        content = response.content.decode()
        assert 'rel="canonical"' in content

    def test_public_page_has_jsonld(self, client, page, owner_user):
        client.force_login(owner_user)
        response = client.get(page.get_absolute_url())
        content = response.content.decode()
        assert "application/ld+json" in content
        assert "BreadcrumbList" in content

    def test_private_page_has_noindex(self, client, private_page, user):
        client.force_login(user)
        response = client.get(private_page.get_absolute_url())
        content = response.content.decode()
        assert "noindex" in content

    def test_private_page_no_jsonld(self, client, private_page, user):
        client.force_login(user)
        response = client.get(private_page.get_absolute_url())
        content = response.content.decode()
        assert "BreadcrumbList" not in content


@pytest.mark.django_db
class TestDirectoryMetaTags:
    def test_public_directory_has_og_tags(
        self, client, root_directory, owner_user
    ):
        client.force_login(owner_user)
        response = client.get(root_directory.get_absolute_url())
        content = response.content.decode()
        assert "og:title" in content
        assert "og:type" in content

    def test_private_directory_has_noindex(
        self, client, private_directory, user
    ):
        client.force_login(user)
        response = client.get(private_directory.get_absolute_url())
        content = response.content.decode()
        assert "noindex" in content
