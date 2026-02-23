"""Diff utilities for comparing page revisions."""

import difflib

from django.utils.html import escape


def _word_diff_line(old_text, new_text):
    """Compute intra-line word-level diffs between two strings.

    Returns (old_html, new_html) with changed segments wrapped in <span>
    tags using darker background colors, like GitHub's diff view.
    """
    sm = difflib.SequenceMatcher(None, old_text, new_text)
    old_parts = []
    new_parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            old_parts.append(escape(old_text[i1:i2]))
            new_parts.append(escape(new_text[j1:j2]))
        elif op == "replace":
            old_parts.append(
                '<span class="bg-red-200 dark:bg-red-800/50 '
                'rounded-sm px-px">'
                f"{escape(old_text[i1:i2])}</span>"
            )
            new_parts.append(
                '<span class="bg-green-200 dark:bg-green-800/50 '
                'rounded-sm px-px">'
                f"{escape(new_text[j1:j2])}</span>"
            )
        elif op == "delete":
            old_parts.append(
                '<span class="bg-red-200 dark:bg-red-800/50 '
                'rounded-sm px-px">'
                f"{escape(old_text[i1:i2])}</span>"
            )
        elif op == "insert":
            new_parts.append(
                '<span class="bg-green-200 dark:bg-green-800/50 '
                'rounded-sm px-px">'
                f"{escape(new_text[j1:j2])}</span>"
            )
    return "".join(old_parts), "".join(new_parts)


def unified_diff(old_content, new_content):
    """Generate an HTML unified diff between two strings.

    Returns color-coded HTML (green for additions, red for deletions)
    with word-level highlighting for changed segments within lines.
    Dark mode aware via Tailwind classes.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="Previous",
            tofile="Current",
            lineterm="",
        )
    )

    html_lines = []
    i = 0
    while i < len(diff):
        line = diff[i]

        if line.startswith("+++") or line.startswith("---"):
            escaped = escape(line.rstrip("\n"))
            html_lines.append(
                f'<div class="text-gray-500 dark:text-gray-400 font-bold">'
                f"{escaped}</div>"
            )
            i += 1
        elif line.startswith("@@"):
            escaped = escape(line.rstrip("\n"))
            html_lines.append(
                f'<div class="text-blue-600 dark:text-blue-400 bg-blue-50'
                f' dark:bg-blue-900/20 px-2">{escaped}</div>'
            )
            i += 1
        elif line.startswith("-") and not line.startswith("---"):
            # Collect consecutive removal lines
            removals = []
            while (
                i < len(diff)
                and diff[i].startswith("-")
                and not diff[i].startswith("---")
            ):
                removals.append(diff[i])
                i += 1
            # Collect consecutive addition lines that follow
            additions = []
            while (
                i < len(diff)
                and diff[i].startswith("+")
                and not diff[i].startswith("+++")
            ):
                additions.append(diff[i])
                i += 1

            # Pair up removals and additions for word-level diff
            paired = min(len(removals), len(additions))
            for j in range(paired):
                old_text = removals[j][1:].rstrip("\n")
                new_text = additions[j][1:].rstrip("\n")
                old_html, new_html = _word_diff_line(old_text, new_text)
                html_lines.append(
                    f'<div class="text-red-700 dark:text-red-400 bg-red-50'
                    f' dark:bg-red-900/20 px-2">-{old_html}</div>'
                )
                html_lines.append(
                    f'<div class="text-green-700 dark:text-green-400 bg-green-50'
                    f' dark:bg-green-900/20 px-2">+{new_html}</div>'
                )

            # Remaining unpaired removals (pure deletions)
            for j in range(paired, len(removals)):
                escaped = escape(removals[j][1:].rstrip("\n"))
                html_lines.append(
                    f'<div class="text-red-700 dark:text-red-400 bg-red-50'
                    f' dark:bg-red-900/20 px-2">-{escaped}</div>'
                )
            # Remaining unpaired additions (pure insertions)
            for j in range(paired, len(additions)):
                escaped = escape(additions[j][1:].rstrip("\n"))
                html_lines.append(
                    f'<div class="text-green-700 dark:text-green-400 bg-green-50'
                    f' dark:bg-green-900/20 px-2">+{escaped}</div>'
                )
        elif line.startswith("+") and not line.startswith("+++"):
            # Standalone addition (not preceded by removal)
            escaped = escape(line[1:].rstrip("\n"))
            html_lines.append(
                f'<div class="text-green-700 dark:text-green-400 bg-green-50'
                f' dark:bg-green-900/20 px-2">+{escaped}</div>'
            )
            i += 1
        else:
            escaped = escape(line.rstrip("\n"))
            html_lines.append(f'<div class="px-2">{escaped}</div>')
            i += 1

    return "\n".join(html_lines)
