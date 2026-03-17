"""Tests for markdown utilities: strip_markdown, render_markdown, internal URL extraction."""

from unittest.mock import patch

from wiki.lib.markdown import (
    extract_all_wiki_slugs,
    extract_slugs_from_internal_urls,
    render_markdown,
    strip_markdown,
)


class TestStripMarkdown:
    def test_plain_text_unchanged(self):
        assert strip_markdown("Hello world") == "Hello world"

    def test_empty_input(self):
        assert strip_markdown("") == ""
        assert strip_markdown(None) == ""

    def test_strips_heading_markers(self):
        result = strip_markdown("# Title\n\nBody text.")
        assert "Title" in result
        assert "#" not in result
        assert "Body text." in result

    def test_strips_fenced_code_blocks(self):
        md = "Before.\n\n```python\nprint('hi')\n```\n\nAfter."
        result = strip_markdown(md)
        assert "print" not in result
        assert "Before." in result
        assert "After." in result

    def test_preserves_inline_code_content(self):
        assert "foo" in strip_markdown("Use `foo` here.")
        assert "`" not in strip_markdown("Use `foo` here.")

    def test_strips_images(self):
        result = strip_markdown("See ![alt](img.png) here.")
        assert "alt" not in result
        assert "img.png" not in result

    def test_converts_links_to_text(self):
        result = strip_markdown("Click [here](https://example.com).")
        assert "here" in result
        assert "https://example.com" not in result
        assert "[" not in result

    def test_strips_bold_and_italic(self):
        result = strip_markdown("This is **bold** and *italic*.")
        assert "bold" in result
        assert "italic" in result
        assert "*" not in result

    def test_strips_strikethrough(self):
        result = strip_markdown("This is ~~deleted~~ text.")
        assert "deleted" in result
        assert "~~" not in result

    def test_strips_html_tags(self):
        result = strip_markdown("Hello <strong>world</strong>.")
        assert "world" in result
        assert "<strong>" not in result

    def test_strips_horizontal_rules(self):
        result = strip_markdown("Above\n\n---\n\nBelow")
        assert "---" not in result
        assert "Above" in result

    def test_strips_blockquotes(self):
        result = strip_markdown("> Quoted\n\nNormal")
        assert ">" not in result
        assert "Quoted" in result

    def test_strips_unordered_list_markers(self):
        result = strip_markdown("- Item one\n- Item two")
        assert "Item one" in result
        assert "- " not in result

    def test_strips_ordered_list_markers(self):
        result = strip_markdown("1. First\n2. Second")
        assert "First" in result
        assert "1." not in result

    def test_collapses_whitespace(self):
        result = strip_markdown("Hello   \n\n  world")
        assert result == "Hello world"


class TestRenderMarkdownAutolink:
    """Bare URLs should be auto-linked in rendered output."""

    def test_bare_url_becomes_link(self):
        html = render_markdown("Visit https://example.com today.")
        assert 'href="https://example.com"' in html
        assert ">https://example.com</a>" in html

    def test_url_inside_markdown_link_not_doubled(self):
        html = render_markdown("[Example](https://example.com)")
        assert html.count("https://example.com") == 1

    def test_bare_http_url(self):
        html = render_markdown("See http://example.com for info.")
        assert 'href="http://example.com"' in html


class TestExtractSlugsFromInternalUrls:
    """extract_slugs_from_internal_urls should find page slugs in content."""

    @patch("wiki.lib.markdown.settings")
    def test_relative_path(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        slugs = extract_slugs_from_internal_urls(
            "See /c/help/my-page for info"
        )
        assert "my-page" in slugs

    @patch("wiki.lib.markdown.settings")
    def test_full_url_matching_domain(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        content = "Link: https://wiki.free.law/c/help/my-page"
        slugs = extract_slugs_from_internal_urls(content)
        assert "my-page" in slugs

    @patch("wiki.lib.markdown.settings")
    def test_full_url_different_domain_ignored(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        content = "Link: https://other.com/c/help/my-page"
        slugs = extract_slugs_from_internal_urls(content)
        assert len(slugs) == 0

    @patch("wiki.lib.markdown.settings")
    def test_markdown_link_with_relative_path(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        content = "[My Page](/c/help/my-page)"
        slugs = extract_slugs_from_internal_urls(content)
        assert "my-page" in slugs

    @patch("wiki.lib.markdown.settings")
    def test_markdown_link_with_full_url(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        content = "[My Page](https://wiki.free.law/c/help/my-page)"
        slugs = extract_slugs_from_internal_urls(content)
        assert "my-page" in slugs

    @patch("wiki.lib.markdown.settings")
    def test_action_urls_ignored(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        content = "Edit at /c/help/my-page/edit"
        slugs = extract_slugs_from_internal_urls(content)
        assert len(slugs) == 0

    @patch("wiki.lib.markdown.settings")
    def test_root_level_page(self, mock_settings):
        mock_settings.BASE_URL = "https://wiki.free.law"
        content = "See /c/my-page for details"
        slugs = extract_slugs_from_internal_urls(content)
        assert "my-page" in slugs


class TestExtractAllWikiSlugs:
    """extract_all_wiki_slugs should find slugs from all wiki link syntaxes."""

    def test_standalone_hash_slug(self):
        assert "my-page" in extract_all_wiki_slugs("See #my-page for info")

    def test_markdown_link_with_hash_slug(self):
        assert "my-page" in extract_all_wiki_slugs(
            "See [my page](#my-page) for info"
        )

    def test_reference_link_with_hash_slug(self):
        slugs = extract_all_wiki_slugs("[ref]: #my-page")
        assert "my-page" in slugs

    def test_all_patterns_combined(self):
        content = (
            "See #standalone-page and [linked](#linked-page).\n\n"
            "[ref]: #ref-page"
        )
        slugs = extract_all_wiki_slugs(content)
        assert slugs == {"standalone-page", "linked-page", "ref-page"}

    def test_no_slugs(self):
        assert extract_all_wiki_slugs("No wiki links here.") == set()


class TestWikiLinkRegexes:
    """Test that wiki link regexes match the correct patterns."""

    def test_standalone_not_matched_in_parens(self):
        """WIKI_LINK_RE should not match #slug inside parentheses."""
        from wiki.lib.markdown import WIKI_LINK_RE

        assert WIKI_LINK_RE.findall("(#some-slug)") == []

    def test_standalone_matched_normally(self):
        from wiki.lib.markdown import WIKI_LINK_RE

        assert WIKI_LINK_RE.findall("See #some-slug here") == ["some-slug"]

    def test_md_link_regex_matches(self):
        from wiki.lib.markdown import _MD_LINK_WIKI_RE

        m = _MD_LINK_WIKI_RE.search("[click here](#my-page)")
        assert m is not None
        assert m.group(1) == "click here"
        assert m.group(2) == "my-page"

    def test_md_link_regex_no_match_for_url(self):
        from wiki.lib.markdown import _MD_LINK_WIKI_RE

        assert _MD_LINK_WIKI_RE.search("[text](https://example.com)") is None

    def test_ref_link_regex_matches(self):
        from wiki.lib.markdown import _REF_LINK_WIKI_RE

        m = _REF_LINK_WIKI_RE.search("[ref]: #my-page")
        assert m is not None
        assert m.group(2) == "my-page"

    def test_ref_link_regex_no_match_for_url(self):
        from wiki.lib.markdown import _REF_LINK_WIKI_RE

        assert _REF_LINK_WIKI_RE.search("[ref]: https://example.com") is None
