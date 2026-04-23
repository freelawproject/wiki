---
title: "Citation Lookup and Verification API"
description: "Trained on over 50 million citations going back centuries, our citation lookup API can translate a citation you have to a link on our site, or it can serve as a guardrail to help identify and prevent hallucinated citations."
redirect_from: "/help/api/rest/v4/citation-lookup/"
wiki_path: "/c/courtlistener/help/api/rest/v4/citation-lookup/"
data_source: "https://www.courtlistener.com/api/rest/v4/wiki-data/"
data_source_cache: 86400
---

## Overview
`/api/rest/v4/citation-lookup/`

<p class="lead">Use this API to look up citations in CourtListener's database of [[ citation_count ]] citations.</p>

This API can look up either an individual citation or can parse and look up every citation in a block of text. This can be useful as a guardrail to help prevent hallucinated citations.

This API uses [Eyecite][eyecite], a tool we developed with [Harvard Library Innovation Lab][lil] to parse legal citations. To develop Eyecite, we analyzed more than 50 million citations going back more than two centuries. We believe we have identified every reporter abbreviation in American case law and that there is no case law citation that Eyecite cannot properly parse and interpret.

This API uses the same authentication and serialization methods as the rest of the CourtListener APIs. It does not support filtering, pagination, ordering, or field selection.

[eyecite]: https://free.law/open-source-tools#eyecite
[lil]: https://lil.law.harvard.edu/

## Usage

The simplest way to query this API is to send it a blob of text. If the text does not have any citations, it will simply return an empty JSON array:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'text=Put some text here'
```

Returns:

```json
[]
```

If the text contains valid citations, it will return a list of the citations, analyzing each. This example contains a single citation that is found:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'text=Obergefell v. Hodges (576 U.S. 644) established the right to marriage among same-sex couples'
```

Which would return:

```json
[
  {
    "citation": "576 U.S. 644",
    "normalized_citations": [
      "576 U.S. 644"
    ],
    "start_index": 22,
    "end_index": 34,
    "status": 200,
    "error_message": "",
    "clusters": [...one large cluster object here...]
  }
]
```

If you have the volume, reporter, and page for a citation, you can look it up as follows:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'volume=576' \
  --data 'reporter=U.S.' \
  --data 'page=644'
```

That returns the same response as above.

## Field Definitions

The fields returned by this API are:

- `citation` — The citation you looked up. If you supplied the volume, reporter, and page, they will appear here as a single space-separated string.

- `normalized_citations` — Normalized versions of your citation if it contains a typo or if it is not the canonical (standard) abbreviation for a reporter. If the citation queried is ambiguous, more than one item can appear in this field. See examples below.

- `start_index` & `end_index` — These fields indicate the start and end positions where a citation is found in the text queried.

- `status` — indicates the outcome of a citation lookup. Its values correspond to HTTP status codes and can have one of five values:

    - `200 (OK)` — We found a citation, it was valid, and we were able to look it up in CourtListener.
    - `404 (Not Found)` — We found a citation, it was valid, but we were unable to look it up in CourtListener.
    - `400 (Bad Request)` — We found something that looks like a citation, but the reporter in the citation wasn't in our system (e.g., "33 Umbrella 422" looks like a citation, but is not valid).
    - `300 (Multiple Choices)` — We found a valid citation, it was valid, but it matched more than one item in CourtListener.
    - `429 (Too Many Requests)` — This API will only lookup [[ citation_lookup.max_per_request ]] citations in a single request. Any citations after that point will have this status. They will be identified but will not be looked up. (See throttles below)

- `error_message` — This field will contain additional details about any problems the lookup encounters.

- `clusters` — This is a list of the CourtListener [cluster objects][cluster-endpoint] that match the citation in your query. This key will contain multiple values when a citation matches more than one legal decision. This can happen when a citation is ambiguous or when multiple decisions are on a single page in a printed book (and thus share the same citation).

[cluster-endpoint]: case-law-api.md#clusters

## Limitations & Throttles

This API has four limitations on how much it can be used:

1. The performance of this API is affected by the number of citations it has to look up. Therefore, it is throttled to [[ citation_lookup.throttle_count ]] valid citations per [[ citation_lookup.throttle_period ]]. If you are below this throttle, you will be able to send a request to the API. If a request pushes you beyond this throttle, further requests will be denied. When your request is denied, the API will respond with a 429 HTTP code and a JSON object. The JSON object will contain a `wait_util` key that uses an ISO-8601 datetime to indicate when you will be able to make your next request.

2. The API will look up at most [[ citation_lookup.max_per_request ]] citations in any single request. Any citations past that point will be parsed, but not matched to the CourtListener database. The `status` key of such citations will be 429, indicating "Too many citations requested." See examples below for details.

3. Text lookup requests to this API can only contain 64,000 characters at a time. Requests with more than this amount will be blocked for security. This is about 50 pages of legal content.

4. To prevent denial of service attacks that do not contain any citations, this API has the same request throttle rates as the other CourtListener APIs. This way, even requests that do not contain citations can be throttled. (Most users will never encounter this throttle.)

A few other limitations to be aware of include:

1. This API does not look up statutes, law journals, id, or supra citations. If you wish to match such citations, please use Eyecite directly.

2. This API will not attempt to match citations without volume numbers or page numbers (e.g. 22 U.S. ___).

## API Examples

### Basic, Valid Lookup

The following is a basic lookup using the `text` parameter and a block of text:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'text=Obergefell v. Hodges (576 U.S. 644) established the right to marriage among same-sex couples'
[
  {
    "citation": "576 U.S. 644",
    "normalized_citations": [
      "576 U.S. 644"
    ],
    "start_index": 22,
    "end_index": 34,
    "status": 200,
    "error_message": "",
    "clusters": [...one cluster here...]
  }
]
```

### Failed Lookup

This query uses the volume-reporter-page triad, but fails because the citation does not exist:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'volume=1' \
  --data 'reporter=U.S.' \
  --data 'page=200'
[
  {
    "citation": "1 U.S. 200",
    "normalized_citations": [
      "1 U.S. 200"
    ],
    "start_index": 0,
    "end_index": 10,
    "status": 404,
    "error_message": "Citation not found: '1 U.S. 200'",
    "clusters": []
  }
]
```

Note that:

1. The `status` field is set to 404 indicating the citation was not found.

2. The `start_index` is 0, and the `end_index` is the length of the citation including space separators.

3. The `error_message` field provides details of the error.

### Throttled Citations

If your request contains more than [[ citation_lookup.max_per_request ]] citations, the 6th and subsequent citations will be returned with 429 `status` fields:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'text=Imagine a very long blob here, with 6 citations.'
[
  ...5 citations would appear here, then the 6th and subsequent citations would be...
  {
    "citation": "576 U.S. 644",
    "normalized_citations": [
      "576 U.S. 644"
    ],
    "start_index": 10002,
    "end_index": 10013,
    "status": 429,
    "error_message": "Too many citations requested.",
    "clusters": []
  }
]
```

Note that:

1. All citations will be parsed and will provide normalized versions and index locations.

2. Citations after the [[ citation_lookup.max_per_request ]]th will return a `status` of 429, indicating "Too many citations requested."

3. A follow-up query that begins on the 6th `start_index` (in this case number 10002) will look up the next [[ citation_lookup.max_per_request ]] items.

### Typoed/Non-Canonical Reporter Abbreviation

If you query the non-canonical reporter abbreviation or if your reporter contains a known typo, we will provide the corrected citation in the `normalized_citations` key. The following example looks up a citation using "US" instead of the correct "U.S.":

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'text=576 US 644'
[
  {
    "citation": "576 US 644",
    "normalized_citations": [
      "576 U.S. 644"
    ],
    "start_index": 1,
    "end_index": 11,
    "status": 200,
    "error_message": "",
    "clusters": [...one cluster here...]
  }
]
```

### Ambiguous Citation

This lookup is for an ambiguous citation abbreviated as "H." This reporter abbreviation can refer to Handy's Ohio Reports, the Hawaii Reports, or Hill's New York Reports. Only two of those reporter series have cases at the queried volume and page number, so the API returns two possible matches for the citation:

```
curl -X POST "https://www.courtlistener.com/api/rest/v4/citation-lookup/" \
  --header 'Authorization: Token <your-token-here>' \
  --data 'text=1 H. 150'
[
  {
    "citation": "1 H. 150",
    "normalized_citations": [
      "1 Handy 150",
      "1 Haw. 150",
      "1 Hill 150"
    ],
    "start_index": 0,
    "end_index": 8,
    "status": 300,
    "clusters": [
      {
        ...
        "citations": [{
          "volume": 1,
          "reporter": "Handy",
          "page": "150",
          "type": 2
        }],
       ...
       "case_name": "Louis v. Steamboat Buckeye",
       ...
      },
      {
        ...
        "citations": [{
          "volume": 1,
          "reporter": "Haw.",
          "page": "150",
          "type": 2
        }],
        ...
        "case_name": "Fell v. Parke",
        ...
      }
    ]
  }
]
```

Note that:

1. The `normalized_citations` field returned three possible values for the ambiguous query.

2. The `status` field returned a 300 code, indicating "Multiple Choices."

3. There are two different objects returned in the `clusters` field.
