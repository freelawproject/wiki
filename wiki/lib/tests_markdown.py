"""Tests for markdown utilities: strip_markdown."""

from wiki.lib.markdown import strip_markdown


class TestStripMarkdown:
    def test_plain_text_unchanged(self):
        assert strip_markdown("Hello world") == "Hello world"

    def test_empty_input(self):
        assert strip_markdown("") == ""
        assert strip_markdown(None) == ""

    def test_strips_headings(self):
        assert "Title" not in strip_markdown("# Title\n\nBody text.")
        assert "Body text." in strip_markdown("# Title\n\nBody text.")

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
