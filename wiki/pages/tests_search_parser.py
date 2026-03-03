"""Unit tests for the search query parser (no database needed)."""

from datetime import date

from wiki.pages.search_parser import parse_query


class TestParseQuery:
    def test_plain_text(self):
        result = parse_query("deploy guide")
        assert result.text == "deploy guide"
        assert result.phrases == []
        assert result.excluded == []

    def test_quoted_phrase(self):
        result = parse_query('"deploy guide" setup')
        assert "deploy guide" in result.phrases
        assert result.text == "setup"

    def test_multiple_phrases(self):
        result = parse_query('"first phrase" "second phrase"')
        assert result.phrases == ["first phrase", "second phrase"]
        assert result.text == ""

    def test_dir_filter(self):
        result = parse_query("setup dir:engineering")
        assert result.directories == ["engineering"]
        assert result.text == "setup"

    def test_owner_filter(self):
        result = parse_query("setup owner:alice")
        assert result.owners == ["alice"]
        assert result.text == "setup"

    def test_visibility_filter(self):
        result = parse_query("setup visibility:public")
        assert result.visibility == "public"
        assert result.text == "setup"

    def test_is_shorthand(self):
        result = parse_query("setup is:private")
        assert result.visibility == "private"

    def test_title_filter(self):
        result = parse_query("title:setup")
        assert result.title_terms == ["setup"]
        assert result.text == ""

    def test_content_filter(self):
        result = parse_query("content:docker")
        assert result.content_terms == ["docker"]

    def test_before_date(self):
        result = parse_query("setup before:2026-01-15")
        assert result.before_date == date(2026, 1, 15)
        assert result.text == "setup"

    def test_after_date(self):
        result = parse_query("setup after:2025-06-01")
        assert result.after_date == date(2025, 6, 1)

    def test_invalid_date_ignored(self):
        result = parse_query("setup before:not-a-date")
        assert result.before_date is None
        assert result.text == "setup"

    def test_exclude_term(self):
        result = parse_query("deploy -draft")
        assert result.excluded == ["draft"]
        assert result.text == "deploy"

    def test_multiple_excludes(self):
        result = parse_query("deploy -draft -wip")
        assert "draft" in result.excluded
        assert "wip" in result.excluded

    def test_colon_inside_quotes_not_parsed(self):
        result = parse_query('"title: with colon"')
        assert "title: with colon" in result.phrases
        assert result.title_terms == []

    def test_mixed_filters_and_text(self):
        result = parse_query(
            'deploy "production guide" dir:engineering owner:alice -draft'
        )
        assert result.text == "deploy"
        assert "production guide" in result.phrases
        assert result.directories == ["engineering"]
        assert result.owners == ["alice"]
        assert "draft" in result.excluded

    def test_empty_query(self):
        result = parse_query("")
        assert result.text == ""
        assert result.phrases == []
        assert result.excluded == []

    def test_whitespace_only_query(self):
        result = parse_query("   ")
        assert result.text == ""

    def test_multiple_dirs(self):
        result = parse_query("setup dir:engineering dir:devops")
        assert result.directories == ["engineering", "devops"]

    def test_empty_quoted_phrase_ignored(self):
        result = parse_query('"" setup')
        assert result.phrases == []
        assert result.text == "setup"
