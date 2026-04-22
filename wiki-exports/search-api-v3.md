---
title: "Search API, v3"
description: "Use this API to search case law, federal filings and cases, judges, and oral argument audio files."
redirect_from: "/help/api/rest/v3/search/"
wiki_path: "/c/courtlistener/help/api/rest/v3/search/"
search_engines: false
ai_assistants: false
---

> [!WARNING]
> **Deprecated** — This is the documentation for the v3 Search API. Please use the [latest version][rest-api] instead.

## Overview
`/api/rest/v3/search/`

Use this API to search case law, PACER data, judges, and oral argument audio recordings.

To get the most out of this API, see our [coverage][coverage] and [advanced operators][advanced-search] documentation.

[coverage]: https://www.courtlistener.com/coverage/


## Basic Usage

This API uses the same GET parameters as the front end of the website. To use this API, place a search query on the front end of the website. That will give you a URL like:

```
https://www.courtlistener.com/q=foo
```

To make this into an API request, copy the GET parameters from this URL to the API endpoint, creating a request like:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  'https://www.courtlistener.com/api/rest/v3/search/?q=foo'
```

That returns:

```json
{
  "count": 2369,
  "next": "https://www.courtlistener.com/api/rest/v3/search/?page=2&q=foo",
  "previous": null,
  "results": [
    {
      "absolute_url": "/opinion/106359/fong-foo-v-united-states/",
      "attorney": "Arthur Richenthal argued the causes for petitioners and filed briefs for petitioner in No. 65. David E. Feller filed briefs for petitioners in No. 64., Solicitor General Cox argued the causes for the United States. With him on the briefs were Assistant Attorney General Miller, Stephen J. Poliak, Beatrice Rosenberg, Philip R. Monahan and J. F. Bishop.",
      "author_id": null,
      "caseName": "Fong Foo v. United States",
      "caseNameShort": "Fong Foo",
      "citation": [
        "7 L. Ed. 2d 629",
        "82 S. Ct. 671",
        "369 U.S. 141",
        "1962 U.S. LEXIS 1600"
      ],
      "citeCount": 357,
      "cites": [
        94515,
        98794,
        100989,
        101974,
        106273,
        253004
      ],
      "cluster_id": 106359,
      "court": "Supreme Court of the United States",
      "court_citation_string": "SCOTUS",
      "court_exact": "scotus",
      "court_id": "scotus",
      "dateArgued": null,
      "dateFiled": "1962-03-19T00:00:00-08:00",
      "dateReargued": null,
      "dateReargumentDenied": null,
      "docketNumber": "64",
      "docket_id": 1153854,
      "download_url": null,
      "id": 106359,
      "joined_by_ids": null,
      "judge": "Harlan, Clark, Whittaker",
      "lexisCite": "1962 U.S. LEXIS 1600",
      "local_path": null,
      "neutralCite": null,
      "non_participating_judge_ids": null,
      "pagerank": null,
      "panel_ids": null,
      "per_curiam": null,
      "scdb_id": "1961-048",
      "sibling_ids": [
        106359,
        9422362,
        9422363,
        9422364
      ],
      "snippet": "\n\n\n    \n369 U.S. 141 (1962)\nFONG FOO ET AL.\nv.\nUNITED STATES.\nNo. 64.\nSupreme Court of United States...",
      "source": "LRU",
      "status": "Precedential",
      "status_exact": "Precedential",
      "suitNature": "",
      "timestamp": "2024-03-01T14:12:07.892000-08:00",
      "type": "010combined"
    },
    ...
```

That's the simple version. Read on to learn the rest.


## Understanding the API

Unlike most APIs on CourtListener, this API is powered by our search engine, not our database.

This means that it does not use the same approach to ordering, filtering, or field definitions as our other APIs, and sending an HTTP `OPTIONS` request won't be useful.


### Setting the Result `type`

The most important parameter in this API is `type`. This parameter sets the type of object you are querying:

| Type | Definition |
|------|------------|
| `o` | Case law opinions |
| `r` | Federal filing documents from PACER |
| `d` | Federal cases (dockets) from PACER |
| `p` | Judges |
| `oa` | Oral argument audio files |

For example, this query searches case law:

```
https://www.courtlistener.com/q=foo&type=o
```

And this query searches federal filings in the PACER system:

```
https://www.courtlistener.com/q=foo&type=r
```

If the `type` parameter is not provided, the default is to search case law.


### Ordering Results

Each search `type` can be sorted by certain fields. These are available on the front end in the ordering drop down, which sets the `order_by` parameter.


### Filtering Results

Results can be filtered with the input boxes provided on the front end or by [advanced query operators][advanced-search] provided to the `q` parameter.

The best way to refine your query is to do so on the front end, and then copy the GET parameters to the API.


### Fields

Unlike most of the fields on CourtListener, many fields on this API are provided in camelCase instead of snake_case. This is to make it easier for users to place queries like:

```
caseName:foo
```

Instead of:

```
case_name:foo
```

All available fields are listed on the [advanced operators help page][advanced-search].

To understand the meaning of a field, find the object in our regular APIs that it corresponds to, and send an HTTP `OPTIONS` request to the API.

For example, the `docketNumber` field in the search engine corresponds to the `docket_number` field in the `docket` API, so an HTTP `OPTIONS` request to that API returns its definition:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v3/dockets/" \
  | jq '.actions.POST.docket_number'
```

After filtering through [`jq`][jq], that returns:

```json
{
  "type": "string",
  "required": false,
  "read_only": false,
  "label": "Docket number",
  "help_text": "The docket numbers of a case, can be consolidated and quite long. In some instances they are too long to be indexed by postgres and we store the full docket in the correction field on the Opinion Cluster."
}
```

[jq]: https://github.com/jqlang/jq


### Special Notes

A few fields deserve special consideration:

1. As in the front end, when the `type` is set to return case law, only published results are returned by default. To include unpublished and other statuses, you need to explicitly request them.

2. The `snippet` field contains the same values as are found on the front end. This uses the HTML5 `<mark>` element to identify up to five matches in a document.

   This field only responds to arguments provided to the `q` parameter. If the `q` parameter is not used, the `snippet` field will show the first 500 characters of the `text` field.


## Monitoring a Query for New Results

To monitor queries for new results, use the Alert API, which will send emails or webhook events when there are new results.

[rest-api]: rest-api.md
[advanced-search]: https://www.courtlistener.com/help/search/
