"""Tests for wiki.lib.markdown_source: fence scanning and tab expansion."""

from wiki.lib.markdown_source import TAB_WIDTH, expand_tabs, fence_scan


class TestFenceScan:
    def test_tracks_fence_state_including_delimiters(self):
        lines = ["a", "```", "b", "```", "c"]
        assert [f for _, _, f in fence_scan(lines)] == [
            False,
            True,
            True,
            True,
            False,
        ]

    def test_shorter_inner_run_does_not_close_longer_fence(self):
        lines = ["````", "```", "x", "```", "````", "after"]
        assert [f for _, _, f in fence_scan(lines)] == [True] * 5 + [False]


class TestExpandTabs:
    def test_no_tabs_returns_same_object(self):
        content = "    four spaces\n- item\n"
        assert expand_tabs(content) is content

    def test_empty_and_none_pass_through(self):
        assert expand_tabs("") == ""
        assert expand_tabs(None) is None

    def test_leading_tabs_become_tab_width_spaces(self):
        assert expand_tabs("\tone\n\t\ttwo") == (
            " " * TAB_WIDTH + "one\n" + " " * (2 * TAB_WIDTH) + "two"
        )

    def test_tabs_expand_to_next_tab_stop_like_markdown2(self):
        # markdown2 reads "ab\tc" as "ab  c": the tab pads to column 4.
        assert expand_tabs("ab\tc") == "ab  c"
        assert expand_tabs("abcd\te") == "abcd    e"

    def test_nested_list_indented_with_tab(self):
        assert expand_tabs("- a\n\t- b\n") == "- a\n    - b\n"

    def test_fenced_code_block_is_left_alone(self):
        content = "para\n\n```make\nall:\n\tgo build\n```\n\tindented\n"
        assert expand_tabs(content) == (
            "para\n\n```make\nall:\n\tgo build\n```\n    indented\n"
        )

    def test_longer_fence_keeps_inner_fence_open(self):
        content = "````md\n```\n\tkeep\n```\n\tstill kept\n````\n\tfix\n"
        assert expand_tabs(content) == (
            "````md\n```\n\tkeep\n```\n\tstill kept\n````\n    fix\n"
        )

    def test_only_fenced_tabs_is_a_no_op(self):
        content = "```\n\tcode\n```\n"
        assert expand_tabs(content) == content

    def test_crlf_lines_keep_their_line_endings(self):
        assert expand_tabs("\ta\r\n\tb\r\n") == "    a\r\n    b\r\n"

    def test_idempotent(self):
        once = expand_tabs("\t- a\n\t\t- b\n")
        assert expand_tabs(once) == once
