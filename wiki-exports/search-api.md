---
title: "Legal Search API"
description: "Use this API to search case law, federal filings and cases, judges, and oral argument audio files."
redirect_from: "/help/api/rest/v4/search/"
wiki_path: "/c/courtlistener/help/api/rest/v4/search/"
---

## Overview
`/api/rest/v4/search/`

<p class="lead">Use this API to search case law, PACER data, judges, and oral argument audio recordings.</p>

To get the most out of this API, see our [coverage][coverage], [advanced operators][search-operators], and [relative date queries][relative-dates] documentation.

[coverage]: https://www.courtlistener.com/help/coverage/
[search-operators]: https://www.courtlistener.com/help/search-operators/
[relative-dates]: https://www.courtlistener.com/help/relative-dates/

## Basic Usage

This API uses the same GET parameters as the front end of the website. To use this API, place a search query on the front end of the website. That will give you a URL like:

```
https://www.courtlistener.com/q=foo
```

To make this into an API request, copy the GET parameters from this URL to the API endpoint, creating a request like:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  'https://www.courtlistener.com/api/rest/v4/search/?q=foo'
```

That returns:

```json
{
  "count": 2343,
    "next": "https://www.courtlistener.com/api/rest/v4/search/?cursor=cz0yMzUuODcxMjUmcz04MDUzNTUzJnQ9byZkPTIwMjQtMDktMTY%3D&q=foo",
    "previous": null,
    "results": [
        {
            "absolute_url": "/opinion/6613686/foo-v-foo/",
            "attorney": "",
            "caseName": "Foo v. Foo",
            "caseNameFull": "Foo v. Foo",
            "citation": [
                "101 Haw. 235",
                "65 P.3d 182"
            ],
            "citeCount": 0,
            "cluster_id": 6613686,
            "court": "Hawaii Intermediate Court of Appeals",
            "court_citation_string": "Haw. App.",
            "court_id": "hawapp",
            "dateArgued": null,
            "dateFiled": "2003-01-10",
            "dateReargued": null,
            "dateReargumentDenied": null,
            "docketNumber": "24158",
            "docket_id": 63544014,
            "judge": "",
            "lexisCite": "",
            "meta": {
                "timestamp": "2024-06-22T10:26:35.320787Z",
                "date_created": "2022-06-26T23:24:18.926040Z",
                "score": {
                    "bm25": 2.1369965
                }
            },
            "neutralCite": "",
            "non_participating_judge_ids": [],
            "opinions": [
                {
                    "author_id": null,
                    "cites": [],
                    "download_url": null,
                    "id": 6489975,
                    "joined_by_ids": [],
                    "local_path": null,
                    "meta": {
                        "timestamp": "2024-06-24T21:14:41.408206Z",
                        "date_created": "2022-06-26T23:24:18.931912Z"
                    },
                    "per_curiam": false,
                    "sha1": "",
                    "snippet": "\nAffirmed in part, reversed in part, vacated and remanded\n",
                    "type": "lead-opinion"
                }
            ],
            "panel_ids": [],
            "panel_names": [],
            "posture": "",
            "procedural_history": "",
            "scdb_id": "",
            "sibling_ids": [
                6489975
            ],
            "source": "U",
            "status": "Published",
            "suitNature": "",
            "syllabus": ""
        },
...
```

That's the simple version. Read on to learn the rest.

## Understanding the API

Unlike most APIs on CourtListener, this API is powered by our search engine, not our database.

This means that it does not use the same approach to ordering, filtering, or field definitions as our other APIs, and sending an HTTP `OPTIONS` request won't be useful.

CourtListener's search results are powered by the [Citegeist Relevancy Engine][citegeist], which supports both keyword search and semantic search.

Semantic search makes it possible to query the case law database using plain language queries, instead of keywords. It can be a better tool for untrained users, while keyword search provides a powerful ranking system with deep pagination that may be more familiar to attorneys.

For a deeper treatment of the pros and cons of these systems, please read [our help page on Citegeist][citegeist].

[citegeist]: https://www.courtlistener.com/help/citegeist/

### Semantic Search vs. Keyword Search

By default, API requests will be handled by our keyword search engine.

To use semantic search instead, special `GET` parameters or `POST` requests are needed. Whether to use `GET` or `POST` depends on the privacy requirements of your application:

- **GET** — If you are able to send search queries to CourtListener, using a `GET` request is best and simplest.

  To use semantic search with a `GET` request, add `semantic=true` to your request, and you will place a semantic query instead of a keyword query. It's that simple.

- **POST** — If regulatory or privacy requirements prevent you from sending search queries to CourtListener — or if you just prefer a more private approach — we have another solution.

  When you use a `GET` request, we receive the query, embed it on our system and calculate results. If you use a `POST` request, you can do the embedding in your system and send us *only* the resulting embedding, instead of sending the query.

  To `POST` pre-computed embeddings to this endpoint, include a JSON body in the POST request:

  ```json
  {
    "embedding": [0.123, 0.456, -0.789, ...]
  }
  ```

  The `embedding` key in your request body is a list of floating-point numbers representing a vector of your query. It should have a length of 768 dimensions and is required for `POST` requests.

  To calculate embeddings, we recommend our [Inception microservice][inception]. For it to work properly, you will need to use [our fine-tuned model][semantic-search-model].

Semantic search is only available for the case law search engine.

[inception]: https://github.com/freelawproject/inception
[semantic-search-model]: https://free.law/2025/03/11/semantic-search

### Setting the Result Type

The most important parameter in this API is `type`. This parameter sets the type of object you are querying:

| Type | Definition |
|------|------------|
| `o` | Case law opinion clusters with nested Opinion documents. |
| `r` | List of Federal cases (dockets) with up to three nested documents. If there are more than three matching documents, the `more_docs` field for the docket result will be `true`. |
| `rd` | Federal filing documents from PACER |
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

Our [Citegeist Relevancy Engine][citegeist] sorts results when you order by relevancy. It uses a combination of factors to provide the most important results first.

If your sorting field has null values, those results will be sorted at the end of the query, regardless of whether you sort in ascending or descending order. For example, if you sort by a date that is null for an opinion, that opinion will go at the end of the result set.

### Filtering Results

Results can be filtered with the input boxes provided on the front end or by [advanced query operators][search-operators] provided to the `q` parameter.

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

All available fields are listed on the [advanced operators help page][search-operators].

To understand the meaning of a field, find the object in our regular APIs that it corresponds to, and send an HTTP `OPTIONS` request to the API.

For example, the `docketNumber` field in the search engine corresponds to the `docket_number` field in the `docket` API, so an HTTP `OPTIONS` request to that API returns its definition:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/" \
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

### Highlighting Results

To enhance performance, results are not highlighted by default. To enable highlighting, include `highlight=on` in your request.

When highlighting is disabled, the first 500 characters of snippet fields are returned for fields `o`, `r`, and `rd`.

### Result Counts

`type=d` and `type=r` use cardinality aggregation to compute the result count. This enhances performance, but has an error of +/-6% if results are over 2000. We recommend noting this in your interface by saying something like, "About 10,000 results."

### Special Notes

A few fields deserve special consideration:

1. As in the front end, when the `type` is set to return case law, only published results are returned by default. To include unpublished and other statuses, you need to explicitly request them.

2. The `snippet` field contains the same values as are found on the front end. This uses the HTML5 `<mark>` element to identify up to five matches in a document.

   This field only responds to arguments provided to the `q` parameter. If the `q` parameter is not used, the `snippet` field will show the first 500 characters of the `text` field.

   This field only displays Opinion text content.

3. The `meta` field in main documents contains the `score` field, which is currently a JSON object that includes the `bm25` score used by Elasticsearch to rank results. Additional scores may be introduced in the future.

## Monitoring a Query for New Results

All query results are cached for ten minutes. This provides instant responses to front-end users who frequently refresh or paginate results.

Because of this, we do not recommend polling as a mechanism for monitoring queries for new results. Instead, use the [Alert API][alert-api], which will send emails or [webhook events][webhooks] when there are new hits.

[alert-api]: alert-api.md
[webhooks]: webhooks.md
