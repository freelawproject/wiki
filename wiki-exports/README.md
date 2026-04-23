# Wiki Import Instructions

These files are exports of CourtListener's API help pages (from `/help/api/*`) being moved to the Free Law Project Wiki at wiki.free.law as part of [issue #7130](https://github.com/freelawproject/courtlistener/issues/7130). Each `.md` file (except this one and `LINK_MAP.md`) is a single wiki page.


## Front Matter Fields

Every exported file has YAML front matter between `---` delimiters. Here is what each field means and how to configure it during import:

- **`title`** — The page title. Display this as the page heading. Do not add an H1 (`#`) in the page content; the title serves that purpose.

- **`description`** — The Open Graph description for the page. Set this in the wiki page's OG description field.

- **`redirect_from`** — The old CourtListener URL path (e.g., `/help/api/rest/v4/`). After import, CourtListener should return a **302 redirect** from this path to the new wiki URL. Every exported page has this field.

- **`wiki_path`** — The target path on the wiki where this page should be created (e.g., `/c/courtlistener/help/api/rest/v4/`). Use this to determine the page's location in the wiki hierarchy.

- **`data_source`** — (Only on some pages) A URL pointing to a JSON API that provides dynamic data for the page. Set this in the wiki page's **Data Source** settings. Currently the only value used is `https://www.courtlistener.com/api/rest/v4/wiki-data/`.

- **`data_source_cache`** — (Only on some pages) Cache duration in seconds for the data source response. Set this in the wiki page's **Data Source** settings alongside the URL. Currently all pages use `86400` (24 hours).

- **`search_engines: false`** — (Only on legacy version pages, e.g., v1/v2/v3 API docs) Set the wiki page setting "Include in search engines?" to **No**.

- **`ai_assistants: false`** — (Only on legacy version pages) Set the wiki page setting "Share with AI assistants?" to **No**.


## Data Connector Placeholders

Some pages use `[[ key ]]` syntax to pull live data from the CourtListener API. These placeholders are rendered at display time by the wiki's data connector feature, not at import time.

The data source URL is `https://www.courtlistener.com/api/rest/v4/wiki-data/` and should be configured in the wiki page's Data Source settings (along with the cache duration), not embedded in the markdown content.

Available placeholder keys and the pages that use them:

| Key | Description | Used in |
|---|---|---|
| `court_count` | Number of jurisdictions in CourtListener | `rest-api.md`, `rest-api-v3.md` |
| `citation_count` | Total citations in the database | `citation-lookup-api.md` |
| `citation_lookup.throttle_count` | Citation lookup throttle limit | `citation-lookup-api.md` |
| `citation_lookup.throttle_period` | Citation lookup throttle time window | `citation-lookup-api.md` |
| `citation_lookup.max_per_request` | Max citations per single request | `citation-lookup-api.md` |


## Inter-page Links

Links between exported pages use **local file references** such as `rest-api.md`, `case-law-api.md#cluster-endpoint`, or `field-help.md#downloads`. The import script should resolve these to the correct wiki paths using the `wiki_path` front matter field from the target file (or via `LINK_MAP.md`).

Links to `https://www.courtlistener.com/...` are **intentionally absolute** — they point to pages that remain on CourtListener (e.g., coverage pages, bulk data, replication, the contact form, the API browser, jurisdiction list). Do not rewrite these.

See `LINK_MAP.md` for the complete mapping of CourtListener URLs to local files and wiki paths.


## Images

Image URLs pointing to `https://www.courtlistener.com/static/...` should be:

1. Downloaded from CourtListener
2. Uploaded to the wiki as media/attachments
3. Rewritten in the markdown to point to the wiki-hosted copy

Preserve the alt text from each image's markdown syntax.

Images appear in these files:
- `rest-api.md` — Data model diagrams (people model, search model, complete model) and Creative Commons badge
- `webhooks-getting-started.md` — Screenshots of the webhook panel, adding endpoints, disabled endpoints, and test modals
- `webhooks.md` — Screenshot of re-enabling a webhook endpoint


## Lead Paragraphs

Some pages have a `<p class="lead">...</p>` tag wrapping their first paragraph. The wiki renders this as a visually prominent introductory paragraph. Keep this HTML as-is during import.


## Button Links

Some pages use the syntax `[text](url){button}` to render a link as a styled button. Keep this syntax as-is during import — the wiki rendering engine handles it.

Files using button links: `rest-api.md`, `alert-api.md`, `migration-guide.md`, `webhooks.md`, `recap-api.md`, `tag-api.md`.


## Special Files

Two files in this directory are **not** wiki pages and should not be imported:

- **`LINK_MAP.md`** — A reference table mapping CourtListener URL paths to local filenames and wiki paths. Use this during import to resolve links and set up redirects, but do not create a wiki page for it.

- **`README.md`** — This file. Import instructions only.


## Legacy Versions

Four files contain older API version documentation:

- `rest-api-v3.md` → `/c/courtlistener/help/api/rest/v3/`
- `rest-api-v2.md` → `/c/courtlistener/help/api/rest/v2/`
- `rest-api-v1.md` → `/c/courtlistener/help/api/rest/v1/`
- `search-api-v3.md` → `/c/courtlistener/help/api/rest/v3/search/`

These have `search_engines: false` and `ai_assistants: false` in their front matter. Import them as wiki pages but configure the page settings to:

- Exclude from search engine indexing (no sitemap entry)
- Exclude from AI assistant sharing (no llms.txt entry)

These pages exist for historical reference only so that old links continue to work.


## Page Hierarchy

Pages should be created at the wiki paths specified in each file's `wiki_path` front matter field:

```
/c/courtlistener/help/api/rest/v4/overview/               ← rest-api.md
/c/courtlistener/help/api/rest/v4/case-law/               ← case-law-api.md
/c/courtlistener/help/api/rest/v4/pacer-data/             ← pacer-api.md
/c/courtlistener/help/api/rest/v4/recap/                  ← recap-api.md
/c/courtlistener/help/api/rest/v4/search/                 ← search-api.md
/c/courtlistener/help/api/rest/v4/judges/                 ← judge-api.md
/c/courtlistener/help/api/rest/v4/financial-disclosures/  ← financial-disclosure-api.md
/c/courtlistener/help/api/rest/v4/oral-arguments/         ← oral-argument-api.md
/c/courtlistener/help/api/rest/v4/citation-lookup/        ← citation-lookup-api.md
/c/courtlistener/help/api/rest/v4/citations/              ← citation-api.md
/c/courtlistener/help/api/rest/v4/alerts/                 ← alert-api.md
/c/courtlistener/help/api/rest/v4/tags/                   ← tag-api.md
/c/courtlistener/help/api/rest/v4/visualizations/         ← visualizations-api.md
/c/courtlistener/help/api/rest/v4/field-help/             ← field-help.md
/c/courtlistener/help/api/rest/v4/migration-guide/        ← migration-guide.md
/c/courtlistener/help/api/rest/change-log/                ← rest-change-log.md
/c/courtlistener/help/api/webhooks/about/                 ← webhooks.md
/c/courtlistener/help/api/webhooks/getting-started/       ← webhooks-getting-started.md
/c/courtlistener/help/api/rest/v1/overview/               ← rest-api-v1.md (legacy)
/c/courtlistener/help/api/rest/v2/overview/               ← rest-api-v2.md (legacy)
/c/courtlistener/help/api/rest/v3/overview/               ← rest-api-v3.md (legacy)
/c/courtlistener/help/api/rest/v3/search/                 ← search-api-v3.md (legacy)
```


## Post-import Checklist

- [ ] **Data placeholders**: Verify all `[[ ]]` placeholders render with live values from the wiki-data API (check `rest-api.md` and `citation-lookup-api.md`)
- [ ] **Inter-page links**: Click through every local file reference link and confirm it resolves to the correct wiki page
- [ ] **Anchor links**: Verify fragment links (e.g., `rest-api.md#field-selection`, `case-law-api.md#cluster-endpoint`) resolve to the correct heading
- [ ] **Images**: Confirm all images display correctly, especially the data model diagrams and webhook screenshots
- [ ] **Button links**: Verify `{button}` syntax renders as styled buttons
- [ ] **302 redirects**: Set up redirects in CourtListener for every `redirect_from` path pointing to the corresponding wiki URL. Multiple CourtListener paths may redirect to the same wiki page (e.g., both `/help/api/rest/v4/case-law/` and `/help/api/rest/v3/case-law/` redirect to the same wiki page)
- [ ] **Legacy page settings**: Confirm pages with `search_engines: false` and `ai_assistants: false` are excluded from the wiki sitemap and llms.txt
- [ ] **Page titles**: Confirm no page has a duplicate H1 — the `title` front matter field is the sole heading
- [ ] **External links**: Spot-check that absolute `https://www.courtlistener.com/...` links still point to live pages on CourtListener
- [ ] **Data source settings**: Confirm the data source URL and cache duration are configured in the wiki page settings for pages that have `data_source` and `data_source_cache` front matter
