---
title: "Legal Citation APIs"
description: "Use these APIs to understand the citation graph in the CourtListener case law database."
redirect_from: "/help/api/rest/v4/citations/"
wiki_path: "/c/courtlistener/help/api/rest/v4/citations/"
---

<p class="lead">Use these APIs to analyze and query the network of citations between legal cases.</p>

These APIs are powered by [Eyecite][eyecite], our tool for identifying citations in legal text. Using that tool, we have identified millions of citations between legal decisions, which you can query using these APIs.

These citations power our visualizations, tables of authorities, citation search, and more.

To look up specific citations, see our [citation lookup and verification API][citation-lookup-api].

[eyecite]: https://free.law/open-source-tools#eyecite
[citation-lookup-api]: citation-lookup-api.md

## Opinions Cited/Citing API
`/api/rest/v4/opinions-cited/`

This endpoint provides an interface into the citation graph that CourtListener provides between opinions in [our case law database][case-law-api].

You can look up the field descriptions, filtering, ordering, and rendering options by making an `OPTIONS` request:

```
curl -v \
  -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions-cited/"
```

That query will return the following filter options:

```json
{
  "id": {
    "type": "NumberRangeFilter",
    "lookup_types": [
      "exact",
      "gte",
      "gt",
      "lte",
      "lt",
      "range"
    ]
  },
  "citing_opinion": {
    "type": "RelatedFilter",
    "lookup_types": "See available filters for 'Opinions'"
  },
  "cited_opinion": {
    "type": "RelatedFilter",
    "lookup_types": "See available filters for 'Opinions'"
  }
}
```

To understand `RelatedFilters`, see our [filtering documentation][filtering].

These filters allow you to filter to the opinions that an opinion cites (its "Authorities" or backward citations) or the later opinions that cite it (forward citations).

For example, opinion `2812209` is the decision in *Obergefell v. Hodges*. To see what it cites:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions-cited/?citing_opinion=2812209"
```

Which returns (in part):

```json
{
  "count": 75,
  "next": "https://www.courtlistener.com/api/rest/v4/opinions-cited/?citing_opinion=2812209&cursor=cD0xMjA5NjAyMg%3D%3D",
  "previous": null,
  "results": [
    {
      "resource_uri": "https://www.courtlistener.com/api/rest/v4/opinions-cited/167909003/",
      "id": 167909003,
      "citing_opinion": "https://www.courtlistener.com/api/rest/v4/opinions/2812209/",
      "cited_opinion": "https://www.courtlistener.com/api/rest/v4/opinions/96405/",
      "depth": 1
    },
    {
      "resource_uri": "https://www.courtlistener.com/api/rest/v4/opinions-cited/167909002/",
      "id": 167909002,
      "citing_opinion": "https://www.courtlistener.com/api/rest/v4/opinions/2812209/",
      "cited_opinion": "https://www.courtlistener.com/api/rest/v4/opinions/2264443/",
      "depth": 1
    },
...
```

To go the other direction, and see what cites *Obergefell*, use the `cited_opinion` parameter instead:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions-cited/?cited_opinion=2812209"
```

That returns (in part):

```json
{
  "count": 403,
  "next": "https://www.courtlistener.com/api/rest/v4/opinions-cited/?cited_opinion=2812209&page=2",
  "previous": null,
  "results": [
    {
      "resource_uri": "https://www.courtlistener.com/api/rest/v4/opinions-cited/213931728/",
      "id": 213931728,
      "citing_opinion": "https://www.courtlistener.com/api/rest/v4/opinions/10008139/",
      "cited_opinion": "https://www.courtlistener.com/api/rest/v4/opinions/2812209/",
      "depth": 4
    },
...
```

Note that:

- The `depth` field indicates how many times the cited opinion is referenced by the citing opinion. In the example above opinion `10008139` references *Obergefell* (`2812209`) four times. This may indicate that *Obergefell* is an important authority for `10008139`.

- Opinions are often published in more than one book or online resource. Therefore, many opinions have more than one citation to them. These are called "parallel citations." We do not have every parallel citation for every decision. This can impact the accuracy of the graph.

- Frequently, we backfill citations, adding a new citation to an older case. When we do this, we do not always re-run our citation linking utility. This means that any later cases that referred to the newly-added citation may not be linked to it for some time.

## Bulk Data

The citation graph is exported once a month as part of our [bulk data system][bulk-data-citations].

If you want to analyze the citation network, that is often the best place to begin.

[case-law-api]: case-law-api.md
[filtering]: rest-api.md#filtering
[bulk-data-citations]: https://www.courtlistener.com/help/api/bulk-data/#citation-data
