---
title: "Case Law APIs"
description: "Use these APIs to gather data from our massive collection of case law."
redirect_from: "/help/api/rest/v4/case-law/"
wiki_path: "/c/courtlistener/help/api/rest/v4/case-law/"
---

<p class="lead">Use these APIs to access our huge and growing database of case law.</p>

To learn more about this collection, including the cases it has and how we get new data each day, see [Case Law Coverage][case-law-coverage].

This data is organized into a number of objects. An overview of these objects is described in this section, and greater detail is provided for each, below.

The four most important objects in this data set are courts, dockets, clusters, and opinions. Together, these hold most of the information from a single case:

- `Court` objects hold information about thousands of courts in this country, including their name, abbreviation, founding date, and more. Every docket is joined to a court to indicate where the case was filed.

- `Docket` objects hold metadata about the case like the date it was initiated or terminated, the docket number, and more. Every cluster is joined to a docket.

- `Cluster` objects group together opinions when a panel hears a case and there is more than one decision, such as a dissent, concurrence, etc. Clusters are an abstraction we created. Every opinion is joined to a cluster.

- `Opinion` objects contain the text of the decision and the metadata related to the individual panel member that wrote it.

Putting this all together, dockets are filed in particular courts and contain clusters of opinions.

If you are looking for a particular piece of metadata, you will find it at the lowest object from the list above where it would not be repeated in the database.

For example, you *could* make the docket number a field of the opinion object. This would be fine until you had more than one opinion in a cluster, or more than one cluster joined to a docket. When that happened, you would wind up repeating the docket number value in each opinion object. Instead, if you make it a field of the docket object, you only have to save it to one place: The docket that binds together the clusters and opinions.

Another example is the opinion text. You *could* make it a field of the cluster, say, but, again, that wouldn't work, since it wouldn't be clear which opinion the text was a part of in a case with a dissent, concurrence, and majority opinion.

There are two other objects in the case law database:

- **Citation** objects link together which opinion objects cite each other. For more information, see the [Citation help page][citation-api].
- **Parenthetical** objects are extracted from the opinion text when a decision explains a citation it relies on as authority. These are not yet available in an API (see [parentheticals issue on GitHub][parentheticals-issue]), but are available as bulk data.

[case-law-coverage]: https://www.courtlistener.com/help/coverage/opinions/
[citation-api]: citation-api.md
[parentheticals-issue]: https://github.com/freelawproject/courtlistener/issues/4082

## The APIs

### Dockets
`/api/rest/v4/dockets/`

`Docket` objects sit at the top of the object hierarchy. In our PACER database, dockets link together docket entries, parties, and attorneys.

In our case law database, dockets sit above `Opinion Clusters`. In our oral argument database, they sit above `Audio` objects.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request:

```
curl -v \
  -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/"
```

To look up a particular docket, use its ID:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/4214664/"
```

The response you get will not list the docket entries, parties, or attorneys for the docket (doing so doesn't scale), but will have many other metadata fields:

```json
{
  "resource_uri": "https://www.courtlistener.com/api/rest/v4/dockets/4214664/",
  "id": 4214664,
  "court": "https://www.courtlistener.com/api/rest/v4/courts/dcd/",
  "court_id": "dcd",
  "original_court_info": null,
  "idb_data": null,
  "clusters": [],
  "audio_files": [],
  "assigned_to": "https://www.courtlistener.com/api/rest/v4/people/1124/",
  "referred_to": null,
  "absolute_url": "/docket/4214664/national-veterans-legal-services-program-v-united-states/",
  "date_created": "2016-08-20T07:25:37.448945-07:00",
  "date_modified": "2024-05-20T03:59:23.387426-07:00",
  "source": 9,
  "appeal_from_str": "",
  "assigned_to_str": "Paul L. Friedman",
  "referred_to_str": "",
  "panel_str": "",
  "date_last_index": "2024-05-20T03:59:23.387429-07:00",
  "date_cert_granted": null,
  "date_cert_denied": null,
  "date_argued": null,
  "date_reargued": null,
  "date_reargument_denied": null,
  "date_filed": "2016-04-21",
  "date_terminated": null,
  "date_last_filing": "2024-05-15",
  "case_name_short": "",
  "case_name": "NATIONAL VETERANS LEGAL SERVICES PROGRAM v. United States",
  "case_name_full": "",
  "slug": "national-veterans-legal-services-program-v-united-states",
  "docket_number": "1:16-cv-00745",
  "docket_number_core": "1600745",
  "pacer_case_id": "178502",
  "cause": "28:1346 Tort Claim",
  "nature_of_suit": "Other Statutory Actions",
  "jury_demand": "None",
  "jurisdiction_type": "U.S. Government Defendant",
  "appellate_fee_status": "",
  "appellate_case_type_information": "",
  "mdl_status": "",
  "filepath_ia": "https://www.archive.org/download/gov.uscourts.dcd.178502/gov.uscourts.dcd.178502.docket.xml",
  "filepath_ia_json": "https://archive.org/download/gov.uscourts.dcd.178502/gov.uscourts.dcd.178502.docket.json",
  "ia_upload_failure_count": null,
  "ia_needs_upload": true,
  "ia_date_first_change": "2018-09-30T00:00:00-07:00",
  "date_blocked": null,
  "blocked": false,
  "appeal_from": null,
  "tags": [
    "https://www.courtlistener.com/api/rest/v4/tag/1316/"
  ],
  "panel": []
}
```

The name of a docket can change in response to the outside world, but the names of clusters do not change. Therefore, we have `case_name` fields on both the docket and the cluster.

For example, a suit filed against the EPA administrator might be captioned *Petroleum Co. v. Regan*. That would go into the case name fields of the docket and any decisions that were issued. But if the administrator resigns before the case is resolved, the docket would get a new case name, *Petroleum Co. v. New Administrator*, while the case name fields on the clusters would not change.

For more information, see the [advanced help on case names][case-names-help].

[case-names-help]: field-help.md#case-names

### Clusters
`/api/rest/v4/clusters/`

This is a major API that provides the millions of `Opinion Clusters` that are available on CourtListener.

As with all other APIs, you can look up the field descriptions, filtering, ordering, and rendering options by making an `OPTIONS` request:

```
curl -v \
  -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/clusters/"
```

A few notes:

- The `id` field of the cluster is used in case law URLs on CourtListener.

- The `sub_opinions` field provides a list of the opinions that are linked to each cluster.

- The `citations` field will contain a list of parallel citations for the cluster. See the [citation API][citation-api] for details.

- There are several fields with judge information, such as `judges`, `panel`, `non_participating_judges`, etc. Some of these fields contain strings and others are linked to records in our [judge API][judge-api]. When we are able to normalize a judge's name into a record in the judge database, we do so. If not, we store their name in a string field for later normalization.

[judge-api]: judge-api.md

### Opinions
`/api/rest/v4/opinions/`

This API contains the text and other metadata about specific decisions.

As with all other APIs, you can look up the field descriptions, filtering, ordering, and rendering options by making an `OPTIONS` request:

> [!WARNING]
> **Listen Up:** When retrieving opinion text, prefer the `html_with_citations` field instead of `plain_text`. The `html_with_citations` field contains the raw text of the decision, and is the most reliable field for most purposes.
>
> Opinion URLs on the CourtListener website contain a `cluster_id`, not an `opinion_id`. If you want to look up a case using that ID, query the Cluster API. See [Finding a Case by URL](#finding-a-case-by-url), below.

```
curl -v \
  -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions/"
```

A few notes:

- The `type` field indicates whether the item is a concurrence, lead opinion, dissent, etc. The values provided for this field are proceeded by numbers so that if they are sorted, they will also be sorted from highest priority to lowest. The most common type of opinion is a "Combined Opinion" this is what we label any opinion that either cannot be identified as a specific type, or that contains more than one type.

- The `download_url` field contains the original location where we scraped the decision. Many courts do not maintain [Cool URIs][cool-uris], so this field is often unreliable.

- The `local_path` field contains the path to the binary file for the decision, if we have one. To use it, see the [advanced help on file download fields][file-downloads-help].

- The `opinions_cited` field has a list of other opinions cited by the one you are reviewing.

- The `ordering_key` field indicates the order of opinions within a cluster. This field is only populated for opinions ingested from Harvard or Columbia sources.

- In general, the best field for the text of a decision is `html_with_citations`, in which each citation has been identified and linked. This is the field that is used in the CourtListener website.

    The following fields are used to generate `html_with_citations`, but are not usually recommended:

    - `html_columbia` will be populated if we got the content from the Columbia collaboration.
    - `html_lawbox` will be populated if we got the content from the Lawbox donation.
    - `xml_harvard` will be populated if the source was Harvard's Caselaw Access Project. This field has a lot of data but is not always perfect due to being created by OCR.
    - `html_anon_2020` will be populated if we got the content from our anonymous source in 2020.
    - `html` will be populated if we got the opinion from a court's website as a Word Perfect or HTML document, or if we got the opinion from Resource.org, which provided HTML documents.
    - `plain_text` will be populated if we got the opinion from a court's website as a PDF or Microsoft Word document.

    Whichever field you choose, please use [Field Selection][field-selection] to omit unnecessary fields. This will make your system faster and ease the load on ours.

[cool-uris]: https://www.w3.org/Provider/Style/URI.html
[file-downloads-help]: field-help.md#file-download-fields
[field-selection]: rest-api.md#field-selection

### Courts
`/api/rest/v4/courts/`

This API contains data about the courts we have in our database, and is joined into nearly every other API so that you can know where an event happened, a judge worked, etc.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

You can generally cache this API. It does not change often.

## API Examples

### Filtering to Opinions in a Court

Opinions are joined to clusters, which join to dockets, and finally to courts. Therefore, one way to get opinions in a specific court is to use a filter like `cluster__docket__court=XYZ` (note the use of double underscores):

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions/?cluster__docket__court=scotus"
```

That returns:

```json
{
  "next": "https://www.courtlistener.com/api/rest/v4/opinions/?cluster__docket__court=scotus&cursor=cD0xMDUxNjI5NA%3D%3D",
  "previous": null,
  "results": [
      {
          "resource_uri": "https://www.courtlistener.com/api/rest/v4/opinions/9973155/",
          "id": 9973155,
    ...
```

Such an approach is fine if all you want is the opinion object, but often you'll want the docket and the cluster too.

In that case, start by getting the dockets with a filter like `court=XYZ`, then use the IDs in those dockets to get clusters and opinions.

For example, this gets the dockets from SCOTUS:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/?court=scotus"
```

The first result contains a `clusters` key like:

```json
"clusters": [
    "https://www.courtlistener.com/api/rest/v4/clusters/9502621/"
],
```

So we can simply get that URL:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/clusters/9502621/"
```

That returns a cluster, which has the following keys:

```json
"docket": "https://www.courtlistener.com/api/rest/v4/dockets/68533094/",
"sub_opinions": [
    "https://www.courtlistener.com/api/rest/v4/opinions/9969234/"
],
```

Finally, GET the links in the `sub_opinions` field to have the complete object:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions/9969234/"
```

### Filtering by Docket Number

If you know a docket number, you can use it to look up a docket, cluster, or opinion:

A docket by docket number:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/?docket_number=23A994"
```

A cluster by docket number:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/clusters/?docket__docket_number=23A994"
```

An opinion by docket number:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/opinions/?cluster__docket__docket_number=23A994"
```

Docket numbers are not unique, so you'll want to add a court filter too:

- For dockets, add: `&court=scotus`
- For clusters, add: `&docket__court=scotus`
- For opinions, add: `&cluster__docket__court=scotus`

You may also find the [search API][search-api] helpful, since it will do fuzzy docket searches.

### Making a Custom Case Law Corpus

A common need by empirical researchers is a collection of case law about a particular topic. To build such a corpus, use the [search API][search-api] to identify cases and use these APIs to download them.

[search-api]: search-api.md

### Finding a Case by URL

If you know the URL of a case, you can find it in the cluster API. For example, *Obergefell v. Hodges* has this URL, with cluster ID `2812209`:

```
https://www.courtlistener.com/opinion/2812209/obergefell-v-hodges/
```

This case can be found in the cluster API using that same ID:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/clusters/2812209/"
```

Opinion IDs do not reliably match cluster IDs.
