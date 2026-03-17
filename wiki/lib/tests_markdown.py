"""Tests for markdown utilities: strip_markdown, render_markdown, internal URL extraction."""

from unittest.mock import patch

import pytest

from wiki.lib.markdown import (
    _convert_alerts,
    _convert_button_links,
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

    def test_standalone_skips_ref_definition_line(self):
        """Standalone replacement must not mangle #slug inside [ref]: #slug."""
        from wiki.lib.markdown import WIKI_LINK_RE

        content = "[food]: #nonexistent-slug"
        # The standalone regex matches #nonexistent-slug ...
        assert WIKI_LINK_RE.search(content) is not None
        # ... but the line is a reference definition, so resolve_wiki_links
        # should leave it alone (tested in TestRefLinkUnknownSlug below).


@pytest.mark.django_db
class TestRefLinkUnknownSlug:
    """Reference-style links with unknown slugs must not be mangled."""

    def test_unknown_ref_slug_not_turned_into_red_span(self):
        """[ref]: #unknown should stay as-is, not become a red span URL."""
        md = "[click here][food]\n\n[food]: #nonexistent-slug"
        html = render_markdown(md)
        # The red span HTML should NOT appear inside an href
        assert "text-red-500" not in html or 'href="' not in html
        # The link text should still appear
        assert "click here" in html

    def test_standalone_slug_still_gets_red_link(self):
        """Standalone #unknown on a normal line should still get red styling."""
        md = "See #nonexistent-slug for details.\n\n[food]: #nonexistent-slug"
        html = render_markdown(md)
        assert "text-red-500" in html
        assert "Page not found" in html


class TestConvertAlerts:
    """GitHub-style alert blockquotes should be converted to styled divs."""

    def test_note_alert(self):
        html = "<blockquote>\n<p>[!NOTE]<br />\nThis is a note.</p>\n</blockquote>"
        result = _convert_alerts(html)
        assert 'class="markdown-alert markdown-alert-note"' in result
        assert 'class="markdown-alert-title"' in result
        assert ">Note<" in result
        assert "This is a note." in result
        assert "<blockquote>" not in result

    def test_tip_alert(self):
        html = (
            "<blockquote>\n<p>[!TIP]<br />\nHelpful advice.</p>\n</blockquote>"
        )
        result = _convert_alerts(html)
        assert "markdown-alert-tip" in result
        assert ">Tip<" in result

    def test_important_alert(self):
        html = (
            "<blockquote>\n<p>[!IMPORTANT]<br />\nKey info.</p>\n</blockquote>"
        )
        result = _convert_alerts(html)
        assert "markdown-alert-important" in result
        assert ">Important<" in result

    def test_warning_alert(self):
        html = (
            "<blockquote>\n<p>[!WARNING]<br />\nBe careful.</p>\n</blockquote>"
        )
        result = _convert_alerts(html)
        assert "markdown-alert-warning" in result
        assert ">Warning<" in result

    def test_caution_alert(self):
        html = "<blockquote>\n<p>[!CAUTION]<br />\nDanger zone.</p>\n</blockquote>"
        result = _convert_alerts(html)
        assert "markdown-alert-caution" in result
        assert ">Caution<" in result

    def test_case_insensitive(self):
        html = "<blockquote>\n<p>[!note]<br />\nLowercase.</p>\n</blockquote>"
        result = _convert_alerts(html)
        assert "markdown-alert-note" in result

    def test_regular_blockquote_unchanged(self):
        html = "<blockquote>\n<p>Just a regular quote.</p>\n</blockquote>"
        result = _convert_alerts(html)
        assert "<blockquote>" in result
        assert "markdown-alert" not in result

    def test_multi_paragraph_alert(self):
        html = (
            "<blockquote>\n<p>[!NOTE]<br />\n"
            "First paragraph.</p>\n\n<p>Second paragraph.</p>\n</blockquote>"
        )
        result = _convert_alerts(html)
        assert "markdown-alert-note" in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_alert_without_br(self):
        """Alert marker without <br> separator should still work."""
        html = "<blockquote>\n<p>[!NOTE]\nContent here.</p>\n</blockquote>"
        result = _convert_alerts(html)
        assert "markdown-alert-note" in result
        assert "Content here." in result


class TestConvertButtonLinks:
    """Links with {button} suffix should be converted to button-styled links."""

    def test_basic_button(self):
        html = '<a href="https://example.com">Click</a>{button}'
        result = _convert_button_links(html)
        assert 'class="btn btn-primary"' in result
        assert "{button}" not in result
        assert ">Click</a>" in result

    def test_button_outline(self):
        html = '<a href="/page">Go</a>{button-outline}'
        result = _convert_button_links(html)
        assert 'class="btn btn-outline"' in result

    def test_button_danger(self):
        html = '<a href="/delete">Delete</a>{button-danger}'
        result = _convert_button_links(html)
        assert 'class="btn btn-danger"' in result

    def test_button_ghost(self):
        html = '<a href="/info">Info</a>{button-ghost}'
        result = _convert_button_links(html)
        assert 'class="btn btn-ghost"' in result

    def test_no_button_suffix_unchanged(self):
        html = '<a href="https://example.com">Click</a>'
        result = _convert_button_links(html)
        assert result == html
        assert "btn" not in result

    def test_button_with_space_before(self):
        html = '<a href="https://example.com">Click</a> {button}'
        result = _convert_button_links(html)
        assert 'class="btn btn-primary"' in result

    def test_preserves_existing_attributes(self):
        html = '<a rel="nofollow" href="/page">Go</a>{button}'
        result = _convert_button_links(html)
        assert 'rel="nofollow"' in result
        assert 'class="btn btn-primary"' in result

    def test_literal_button_text_not_after_link(self):
        html = "<p>Use {button} syntax for buttons.</p>"
        result = _convert_button_links(html)
        assert result == html


class TestAlertEndToEnd:
    """Test alert rendering through the full render_markdown pipeline."""

    def test_note_renders(self):
        md = "> [!NOTE]\n> This is a note about something."
        html = render_markdown(md)
        assert "markdown-alert-note" in html
        assert "Note" in html
        assert "This is a note about something." in html

    def test_mixed_content(self):
        md = "Some text.\n\n> [!WARNING]\n> Be careful here.\n\nMore text."
        html = render_markdown(md)
        assert "markdown-alert-warning" in html
        assert "Some text." in html
        assert "More text." in html


class TestButtonEndToEnd:
    """Test button link rendering through the full render_markdown pipeline."""

    def test_button_renders(self):
        md = "[Click here](https://example.com){button}"
        html = render_markdown(md)
        assert 'class="btn btn-primary"' in html
        assert 'href="https://example.com"' in html

    def test_button_outline_renders(self):
        md = "[Secondary](https://example.com){button-outline}"
        html = render_markdown(md)
        assert 'class="btn btn-outline"' in html


class TestStripMarkdownAlerts:
    """strip_markdown should remove alert markers."""

    def test_strips_note_marker(self):
        result = strip_markdown("> [!NOTE]\n> Important info here.")
        assert "[!NOTE]" not in result
        assert "Important info here." in result

    def test_strips_warning_marker(self):
        result = strip_markdown("> [!WARNING]\n> Be careful.")
        assert "[!WARNING]" not in result
        assert "Be careful." in result


class TestStripMarkdownButtons:
    """strip_markdown should remove {button} suffixes."""

    def test_strips_button(self):
        result = strip_markdown("[Click](https://example.com){button}")
        assert "{button}" not in result
        assert "Click" in result

    def test_strips_button_outline(self):
        result = strip_markdown("[Go](/page){button-outline}")
        assert "{button-outline}" not in result
        assert "Go" in result

    def test_strips_button_danger(self):
        result = strip_markdown("[Delete](/x){button-danger}")
        assert "{button-danger}" not in result
