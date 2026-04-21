# Directory-Scoped Slugs

## Goal

Allow the same slug in different directories. Eliminate the global slug-uniqueness constraint, support path-qualified wiki links (`#dir/slug`), and automatically rewrite existing links when a collision is introduced.

## Background

Today, slugs are globally unique across all active pages (enforced by a conditional `UniqueConstraint` in `wiki/pages/models.py`). This forces ugly `-2` / `-3` suffixes when unrelated pages in different directories happen to share a title (e.g., "Overview", "Getting Started").

The constraint exists because the wiki link syntax is `#slug` — a bare slug with no directory context, resolved globally in `wiki/lib/markdown.py`. Moving to directory-scoped slugs requires a strategy for disambiguating wiki links.

## Approach

Rather than resolving ambiguity at render time (with a canonical-slug flag or first-wins rule), we prevent ambiguity at write time: when a collision is introduced, the daemon rewrites existing pages' markdown to use the qualified `#dir/slug` form. Authors typing an ambiguous `#slug` in the editor get a dropdown and pick a target, which saves in qualified form.

This turns a data-model problem into a mechanical content-refactor problem, similar to an IDE rename refactor.

## Phase 1 — Markdown extractor cleanup (prerequisite)

Ship this first, independent of the schema change. These are pre-existing issues that must be fixed before anything else is safe.

- **Skip code blocks and inline backticks** in `extract_all_wiki_slugs()` and `extract_slugs_from_internal_urls()` (`wiki/lib/markdown.py`). Links inside triple-backtick fences or inline backticks are currently extracted and would be clobbered by later rewrites.
- **Preserve URL fragments** through link resolution:
  - `_MD_LINK_WIKI_RE` and `_REF_LINK_WIKI_RE`: allow optional `(?:#[a-z0-9-]+)?` tail after the slug; preserve through rendering.
  - `_INTERNAL_URL_RE` slug extraction: strip `#fragment` before taking the last path segment.
- Add tests for each of the above.

## Phase 2 — Schema changes

- **`Page`**: drop `UniqueConstraint(fields=["slug"], condition=Q(is_deleted=False))`; add `UniqueConstraint(fields=["directory", "slug"], condition=Q(is_deleted=False))`.
- **`SlugRedirect`**: add `directory` FK (nullable for root). Unique key becomes `(directory, old_slug)`.
- **`BackgroundTask`** (new, generic):
  - `type` (string), `payload` (JSONField), `status` (pending/running/done/failed), `attempts` (int), `scheduled_for` (datetime), `last_error` (text), timestamps.
  - Index on `(status, scheduled_for)`.
- Migration: slugs are already globally unique, so the constraint swap has zero data conflicts. `SlugRedirect` backfill populates `directory` from the target page's current directory.

## Phase 3 — Markdown parser support for qualified links

- Extend `WIKI_LINK_RE`, `_MD_LINK_WIKI_RE`, `_REF_LINK_WIKI_RE` to accept `#dir/slug` and `#dir/sub/slug` in addition to `#slug`.
- `resolve_wiki_links` and supporting extractors resolve qualified tokens against `(directory, slug)`.
- Renderer tiebreaker for unqualified `#slug` when multiple match: `.order_by("created_at").first()`. Handles the brief async window and unambiguous cases consistently.
- Slug generation (`Page.save`) switches collision check to `(directory, slug)` scope.

## Phase 4 — URL resolution

- `resolve_path` view matches literally:
  1. Page at exact `(directory_path, slug)`.
  2. Directory at exact path.
  3. `SlugRedirect` at exact `(directory, old_slug)`.
  4. 404.
- No shortlink fallthrough. `page_path_conflicts_with_directory()` still enforces mutual exclusion per path.

## Phase 5 — Collision detection and async rewrites

- In `Page.save()`, after the save, detect if this page introduced a duplicate slug (another active page shares `slug` in a different directory).
- If so, for every page in the other page's `incoming_links`, enqueue a `BackgroundTask` with `type="rewrite_wiki_links"`, payload `{from_page_id, target_page_id}`.
- Daemon worker (`wiki/pages/tasks.py`, integrated into `run_daemon`):
  - Polls `BackgroundTask` where `status="pending"` and `scheduled_for <= now`.
  - For each rewrite task:
    - Re-check state: if the collision no longer exists (target deleted, slug changed), mark done and skip.
    - Load `from_page` markdown, rewrite matching link tokens (`#slug` / `[text](#slug)` / `[ref]: #slug` / `/c/slug`) to qualified form based on the target page's current path.
    - Save inside `transaction.atomic()`. Revision `created_by` is a dedicated system user.
    - Skip notification helpers (subscriptions, etc.) — they live outside the transaction anyway, so this is just "don't invoke them."
    - On optimistic-lock conflict with an active editor, the save just wins; the editor hits the normal merge-required flow on their next submit.

## Phase 6 — Editor UX

When an author types `#slug` and multiple pages match, the existing autocomplete/dropdown shows all matches with their directory path. Selection writes the qualified form into the source.

## Phase 6.5 — Help page updates

In `wiki/pages/management/commands/seed_help_pages.py`:

- **Wiki link syntax section** (around line 367): document the three forms.
  - `#slug` — works when unambiguous across the wiki.
  - `#dir/slug` or `#dir/sub/slug` — use when multiple pages share a slug; also always works.
  - `#slug#section` / `#dir/slug#section` — link to a specific heading on the target page.
- **Autocomplete behavior** (around line 379): when a typed `#slug` matches multiple pages, the dropdown shows each with its directory path; selection inserts the qualified form.
- **What links here** (line 408): no behavior change, but mention that links are tracked regardless of which form was used in the source.
- **Permission warnings** (line 551) and **delete/move** references (lines 789, 923): update prose to reflect qualified-link possibility, no functional change.
- **Overview/index page references** (lines 111, 131, 202): mention the `#dir/slug` form exists; default examples stay with plain `#slug` since that's still the common case.

Keep edits minimal — no new standalone help page, just folded into the existing linking-pages doc.

## Phase 7 — Tests

- Round-trip: create two pages with the same slug in different directories, confirm both resolve.
- Rewrite task: create collision, run daemon, assert linking pages' markdown now uses qualified form.
- Renderer tiebreaker: during a mid-rewrite state, unqualified `#slug` resolves to the `created_at`-oldest match.
- URL resolver: literal path matching with page / directory / `SlugRedirect` fallthrough.
- Fragment preservation: `#slug#section`, `[text](#slug#section)`, `/c/dir/slug#section` all render with the fragment intact and track `PageLink` correctly.
- Code block escape: wiki-link-looking text inside triple backticks and inline backticks is not extracted.

## Order of merge

1. Phase 1 alone — safe, independently valuable.
2. Phases 2–4 together behind a feature branch, migration-tested on a DB snapshot.
3. Phase 5 + the `BackgroundTask` daemon loop.
4. Phase 6 + 6.5 UX and docs polish.
5. Phase 7 tests grow alongside each phase, not at the end.

## Non-goals

- **DirectoryRedirect table**: moving a directory still breaks direct URLs and full-path wiki links. Pre-existing issue; out of scope.
- **Tracking broken/unresolved links**: pre-existing pages that link to a nonexistent `#overview` will begin resolving to a newly-created page with that slug. Acceptable consequence of having broken links in the first place.
- **Wiki links in comments and proposals**: those fields are plain text today; no change.
- **Retry mechanism for locked pages**: rewrites proceed immediately and rely on optimistic locking. Active editors get the standard merge-required flow on rare conflicts.
