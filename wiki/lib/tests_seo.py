"""Tests for SEO infrastructure: descriptions, middleware, sitemaps, robots.txt."""

import json

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from wiki.directories.models import Directory
from wiki.lib.middleware import SEOHeadersMiddleware
from wiki.lib.seo import (
    build_article_jsonld,
    build_breadcrumbs_jsonld,
    extract_description,
)
from wiki.pages.models import Page

# ── extract_description ──────────────────────────────────────────────


class TestExtractDescription:
    def test_plain_text(self):
        assert extract_description("Hello world") == "Hello world"

    def test_strips_headings(self):
        md = "# Title\n\nSome paragraph text here."
        result = extract_description(md)
        assert not result.startswith("#")
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
        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/admin/")
        response = middleware(request)
        assert response["X-Robots-Tag"] == "noindex, nofollow"

    def test_noindex_on_api_path(self):
        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/api/something")
        response = middleware(request)
        assert response["X-Robots-Tag"] == "noindex, nofollow"

    def test_noindex_when_view_sets_flag(self):
        def get_response(request):
            request.seo_noindex = True
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/c/private-page")
        response = middleware(request)
        assert response["X-Robots-Tag"] == "noindex, nofollow"

    def test_no_noindex_on_public_content(self):
        def get_response(request):
            return HttpResponse("ok")

        middleware = self._make_middleware(get_response)
        request = self._make_request("/c/public-page")
        response = middleware(request)
        assert "X-Robots-Tag" not in response

    def test_canonical_header(self):
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

    def test_sitemap_includes_public_page_in_private_directory(
        self, client, user
    ):
        """Under inheritance, a page with explicit visibility=public is included."""
        private_dir = Directory.objects.create(
            path="private-dir",
            title="Private Dir",
            visibility=Directory.Visibility.PRIVATE,
        )
        Page.objects.create(
            title="Hidden Page",
            slug="hidden-page",
            content="Explicitly public",
            directory=private_dir,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "hidden-page" in content


# ── Raw markdown headers ─────────────────────────────────────────────


@pytest.mark.django_db
class TestRawMarkdownHeaders:
    def test_raw_markdown_has_noindex_header(self, client, page, owner_user):
        """The .md endpoint should have X-Robots-Tag: noindex."""
        client.force_login(owner_user)
        response = client.get(f"{page.get_absolute_url()}.md")
        assert response.status_code == 200
        assert response["X-Robots-Tag"] == "noindex"

    def test_raw_markdown_has_canonical_header(self, client, page, owner_user):
        """The .md endpoint should have a Link canonical header."""
        client.force_login(owner_user)
        response = client.get(f"{page.get_absolute_url()}.md")
        assert response.status_code == 200
        assert 'rel="canonical"' in response["Link"]
        assert page.get_absolute_url() in response["Link"]
        assert ".md" not in response["Link"]


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


# ── Article JSON-LD ──────────────────────────────────────────────────


class TestArticleJsonLd:
    def test_basic_article(self, page):
        result = json.loads(
            build_article_jsonld(page, "Test desc", "https://wiki.free.law")
        )
        assert result["@context"] == "https://schema.org"
        assert result["@type"] == "Article"
        assert result["headline"] == page.title
        assert result["description"] == "Test desc"
        assert (
            result["url"] == f"https://wiki.free.law{page.get_absolute_url()}"
        )
        assert "datePublished" in result
        assert "dateModified" in result
        assert result["publisher"]["name"] == "Free Law Project"


@pytest.mark.django_db
class TestPageArticleJsonLd:
    def test_public_page_has_article_jsonld(self, client, page, owner_user):
        client.force_login(owner_user)
        response = client.get(page.get_absolute_url())
        content = response.content.decode()
        assert '"@type": "Article"' in content
        assert '"Free Law Project"' in content

    def test_private_page_no_article_jsonld(self, client, private_page, user):
        client.force_login(user)
        response = client.get(private_page.get_absolute_url())
        content = response.content.decode()
        assert '"@type": "Article"' not in content


# ── SEO description ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestSeoDescription:
    def test_seo_description_used_in_og_tags(self, client, user, owner_user):
        """When seo_description is set, it should appear in OG tags."""
        page = Page.objects.create(
            title="SEO Page",
            slug="seo-page",
            content="Long content that would be auto-extracted.",
            seo_description="Custom SEO summary",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(owner_user)
        response = client.get(page.get_absolute_url())
        content = response.content.decode()
        assert "Custom SEO summary" in content

    def test_auto_description_when_seo_empty(self, client, page, owner_user):
        """When seo_description is blank, content is auto-extracted."""
        client.force_login(owner_user)
        response = client.get(page.get_absolute_url())
        content = response.content.decode()
        assert "og:description" in content


# ── llms.txt ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLlmsTxt:
    def test_llms_txt_status_and_content_type(self, client):
        response = client.get("/llms.txt")
        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain"

    def test_llms_txt_has_noindex(self, client):
        response = client.get("/llms.txt")
        assert response["X-Robots-Tag"] == "noindex"

    def test_llms_txt_includes_public_page(self, client, user):
        Page.objects.create(
            title="Public LLM Page",
            slug="public-llm-page",
            content="Some content.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_llms_txt=Page.LlmsTxtStatus.INCLUDE,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Public LLM Page" in content
        assert "public-llm-page.md" in content

    def test_llms_txt_excludes_private_page(self, client, user):
        Page.objects.create(
            title="Private LLM Page",
            slug="private-llm-page",
            content="Secret.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Private LLM Page" not in content

    def test_llms_txt_uses_seo_description(self, client, user):
        Page.objects.create(
            title="Described Page",
            slug="described-page",
            content="Fallback content.",
            seo_description="Custom LLM description",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_llms_txt=Page.LlmsTxtStatus.INCLUDE,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Custom LLM description" in content

    def test_llms_txt_has_header(self, client):
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert content.startswith("# FLP Wiki")

    def test_llms_txt_excludes_page_with_exclude_status(self, client, user):
        Page.objects.create(
            title="Excluded LLM Page",
            slug="excluded-llm-page",
            content="Some content.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_llms_txt=Page.LlmsTxtStatus.EXCLUDE,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Excluded LLM Page" not in content

    def test_llms_txt_optional_page_in_optional_section(self, client, user):
        Page.objects.create(
            title="Optional LLM Page",
            slug="optional-llm-page",
            content="Some content.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_llms_txt=Page.LlmsTxtStatus.OPTIONAL,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Optional LLM Page" in content
        # Should be after the Optional heading
        assert "## Optional" in content
        optional_pos = content.index("## Optional")
        page_pos = content.index("Optional LLM Page")
        assert page_pos > optional_pos

    def test_llms_txt_directory_exclude_cascades(self, client, user):
        """A page with in_llms_txt=include is excluded when its dir excludes."""
        root = Directory.objects.get_or_create(
            path="",
            defaults={
                "title": "Home",
                "visibility": Directory.Visibility.PUBLIC,
            },
        )[0]
        excluded_dir = Directory.objects.create(
            path="no-llm",
            title="No LLM",
            parent=root,
            visibility=Directory.Visibility.PUBLIC,
            in_llms_txt=Directory.LlmsTxtStatus.EXCLUDE,
        )
        Page.objects.create(
            title="Cascade Excluded Page",
            slug="cascade-excluded",
            content="Content.",
            directory=excluded_dir,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_llms_txt=Page.LlmsTxtStatus.INCLUDE,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Cascade Excluded Page" not in content

    def test_llms_txt_directory_optional_does_not_downgrade_include(
        self, client, user
    ):
        """Under inheritance, a page's own explicit in_llms_txt takes effect."""
        root = Directory.objects.get_or_create(
            path="",
            defaults={
                "title": "Home",
                "visibility": Directory.Visibility.PUBLIC,
            },
        )[0]
        optional_dir = Directory.objects.create(
            path="opt-dir",
            title="Opt Dir",
            parent=root,
            visibility=Directory.Visibility.PUBLIC,
            in_llms_txt=Directory.LlmsTxtStatus.OPTIONAL,
        )
        Page.objects.create(
            title="Kept Page",
            slug="kept-page",
            content="Content.",
            directory=optional_dir,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_llms_txt=Page.LlmsTxtStatus.INCLUDE,
        )
        response = client.get("/llms.txt")
        content = response.content.decode()
        assert "Kept Page" in content
        # Should appear in main section (before Optional), not downgraded
        if "## Optional" in content:
            optional_pos = content.index("## Optional")
            page_pos = content.index("Kept Page")
            assert page_pos < optional_pos

    def test_robots_txt_allows_llms_txt(self, client):
        response = client.get("/robots.txt")
        content = response.content.decode()
        assert "Allow: /llms.txt" in content


# ── Sitemap in_sitemap controls ─────────────────────────────────────


@pytest.mark.django_db
class TestSitemapInSitemapField:
    def test_page_excluded_when_in_sitemap_false(self, client, user):
        Page.objects.create(
            title="No Sitemap Page",
            slug="no-sitemap-page",
            content="Content.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_sitemap="exclude",
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "no-sitemap-page" not in content

    def test_page_included_when_in_sitemap_include(self, client, user):
        Page.objects.create(
            title="Sitemap Page",
            slug="sitemap-page",
            content="Content.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_sitemap=Page.SitemapStatus.INCLUDE,
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "sitemap-page" in content

    def test_inheriting_page_excluded_when_directory_excluded(
        self, client, user
    ):
        """A page with in_sitemap='inherit' in an excluded directory
        does not appear in the sitemap."""
        root = Directory.objects.get_or_create(
            path="",
            defaults={
                "title": "Home",
                "visibility": Directory.Visibility.PUBLIC,
            },
        )[0]
        no_sitemap_dir = Directory.objects.create(
            path="hidden-dir",
            title="Hidden Dir",
            parent=root,
            visibility=Directory.Visibility.PUBLIC,
            in_sitemap="exclude",
        )
        Page.objects.create(
            title="Inheriting Child",
            slug="inheriting-child",
            content="Content.",
            directory=no_sitemap_dir,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_sitemap="inherit",
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "inheriting-child" not in content

    def test_explicit_include_overrides_directory_exclude(self, client, user):
        """A page with explicit in_sitemap='include' appears in the
        sitemap even if its directory is excluded."""
        root = Directory.objects.get_or_create(
            path="",
            defaults={
                "title": "Home",
                "visibility": Directory.Visibility.PUBLIC,
            },
        )[0]
        excluded_dir = Directory.objects.create(
            path="excl-dir",
            title="Excluded Dir",
            parent=root,
            visibility=Directory.Visibility.PUBLIC,
            in_sitemap="exclude",
        )
        Page.objects.create(
            title="Override Page",
            slug="override-page",
            content="Content.",
            directory=excluded_dir,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
            in_sitemap="include",
        )
        response = client.get("/sitemap.xml")
        content = response.content.decode()
        assert "override-page" in content
