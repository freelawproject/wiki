"""Helpers that operate on raw markdown *source*, before rendering.

Kept free of model imports so ``wiki.pages.models`` and
``wiki.directories.models`` can import from here at module top level —
``wiki.lib.markdown`` itself imports those models, which is why it can
only be reached from them via inline imports.
"""

import re

# markdown2's default ``tab_width``: a tab in page content renders as if
# it reached the next multiple of four columns, so that is the width we
# expand to when replacing one.
TAB_WIDTH = 4

_FENCE_LINE_RE = re.compile(r"^\s*(`{3,})")


def fence_scan(lines):
    """Yield (index, line, in_fence) with length-aware fence tracking.

    Mirrors markdown2's rule: a fence closes only on a backtick run at
    least as long as the one that opened it, so an outer ```` fence
    wrapping a literal ``` example stays open across the inner fences.
    Delimiter lines themselves report ``in_fence=True``.
    """
    fence_len = 0
    for i, line in enumerate(lines):
        delim = _FENCE_LINE_RE.match(line)
        if delim:
            run = len(delim.group(1))
            if not fence_len:
                fence_len = run
            elif run >= fence_len:
                fence_len = 0
            yield i, line, True
            continue
        yield i, line, bool(fence_len)


def expand_tabs(content):
    """Replace tab characters in markdown source with spaces.

    Tabs are expanded to the next TAB_WIDTH column, the same way markdown2
    reads them, so rendering is unchanged — only the stored source
    differs. Lines inside fenced code blocks are left alone: a tab there
    is part of the quoted code (a Makefile recipe, a Go snippet) and
    rewriting it would change what the reader copies out.

    Returns ``content`` itself when it holds no tabs, so callers can use
    identity or equality to detect a no-op.
    """
    if not content or "\t" not in content:
        return content
    lines = content.split("\n")
    out = []
    for _, line, in_fence in fence_scan(lines):
        if in_fence or "\t" not in line:
            out.append(line)
            continue
        out.append(line.expandtabs(TAB_WIDTH))
    return "\n".join(out)
