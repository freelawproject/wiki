---
title: "PACER Data APIs"
description: "Use these APIs to query parties, dockets, and filings in the RECAP Archive of PACER data. This is sourced from federal district, appellate, and bankruptcy courts."
redirect_from: "/help/api/rest/v4/pacer/"
wiki_path: "/c/courtlistener/help/api/rest/v4/pacer-data/"
---

<p class="lead">Use these APIs to access almost half a billion items we have in our collection of PACER data.</p>

To learn more about what's in the collection and how we gather PACER data each day, see [our coverage page on the topic.][recap-coverage]

This data is organized into a number of objects. An overview of these objects is described in this section, and greater detail is provided for each, below.

In any legal proceeding, there are roughly three things: Documents, people, and organizations. Documents are grouped together into docket entries, which are grouped together into dockets. People and organizations are examples of parties. Parties have attorneys who act on their behalf in particular ways, which we call the attorney's role in the case.

Each of these relationships is interlinked and has metadata that describes it. Use these APIs to explore this data.

[recap-coverage]: https://www.courtlistener.com/help/coverage/recap/

## Dockets, Courts, Docket Entries, and Documents

A docket is a list of docket entries and some metadata. Each docket entry is a collection of documents that is uploaded to the court by a party or their attorney at a given time.

The endpoints described in this section explain these objects and how they can be accessed in our system.

### Dockets
`/api/rest/v4/dockets/`

`Docket` objects sit at the top of the object hierarchy. In our PACER database, dockets link together docket entries, parties, and attorneys.

In our case law database, dockets sit above `Opinion Clusters`. In our oral argument database, they sit above `Audio` objects.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request:

```
curl -v \
  -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "http://localhost:8000/api/rest/v4/dockets/"
```

To look up a particular docket, use its ID:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "http://localhost:8000/api/rest/v4/dockets/4214664/"
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

Ideally, docket entries, parties, and attorneys would be nested within the docket object you request, but this is not possible because some dockets have a vast number of these objects. Listing so many values in a single response from the server is impractical. To access docket entries, parties, or attorneys for a specific docket, use the docket entry, party, or attorney endpoints and filter by docket ID.

The court fields are references to our Court API, described below.

### Courts
`/api/rest/v4/courts/`

This API contains data about the courts we have in our database, and is joined into nearly every other API so that you can know where an event happened, a judge worked, etc.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

You can generally cache this API. It does not change often.

### Docket Entries
`/api/rest/v4/docket-entries/`

`Docket Entry` objects represent the rows on a PACER docket, and contain one or more nested documents. This follows the design on PACER, in which a single row on a docket represents a document with its associated attachments.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

To filter to the docket entries for a particular docket use the `docket` filter:

### Documents
`/api/rest/v4/recap-documents/`

Each docket entry contains several documents, which we call `RECAP Document` objects.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

A few field-level notes:

| Field | Notes |
|---|---|
| `plain_text` | This field contains the extracted text of the document. We use [Doctor][doctor] to complete this task. If needed, Doctor uses an optimized version of Tesseract to complete OCR. To see whether OCR was used, check the `ocr_status` field. If you don't need this content, omit it via [Field Selection][field-selection] to significantly reduce response times and payload size. |
| `filepath_local` | This field contains the path to the binary file if we have it (`is_available=True`). To use this field, see the [help article on this topic][file-downloads-help]. The name of this field dates back to when all our files were locally stored on a single server. |

This endpoint is only available to select users. Please [get in touch][contact] to access this API.

[doctor]: https://free.law/open-source-tools#doctor
[field-selection]: rest-api.md#field-selection
[file-downloads-help]: field-help.md#file-download-fields

### Parties
`/api/rest/v4/parties/`

The `Party` endpoint provides details about parties that have been involved in federal cases in PACER, and contains nested attorney information.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

This API can be filtered by docket ID to show all the parties for a particular case.

> [!WARNING]
> **Listen Up:** Filters applied to this endpoint only affect the top-level data, not the data nested records within it. Therefore, each party returned by this API will list all the attorneys that have represented them in any case, even if the parties themselves are filtered to a particular case.
>
> To filter the nested attorney data for each party, include the `filter_nested_results=True` parameter in your API request.

For example, this query returns the parties for docket number `123`:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/parties/?docket=123"
```

It returns something like:

```json
{
  "next": "https://www.courtlistener.com/api/rest/v4/parties/?docket=123&cursor=cD0xMjA5NjAyMg%3D%3D&docket=4214664",
  "previous": null,
  "results": [
    {
      "resource_uri": "https://www.courtlistener.com/api/rest/v4/parties/42/",
      "id": 42,
      "attorneys": [
        {
          "attorney": "https://www.courtlistener.com/api/rest/v4/attorneys/1/",
          "attorney_id": 1,
          "date_action": null,
          "docket": "https://www.courtlistener.com/api/rest/v4/dockets/123/",
          "docket_id": 123,
          "role": 10
        },
        {
          "attorney": "https://www.courtlistener.com/api/rest/v4/attorneys/2/",
          "attorney_id": 2,
          "date_action": null,
          "docket": "https://www.courtlistener.com/api/rest/v4/dockets/456/",
          "docket_id": 456,
          "role": 2
        }
      ],
      "party_types": [
        {
          "docket": "https://www.courtlistener.com/api/rest/v4/dockets/123/",
          "docket_id": 123,
          "name": "Plaintiff",
          "date_terminated": null,
          "extra_info": "",
          "highest_offense_level_opening": "",
          "highest_offense_level_terminated": "",
          "criminal_counts": [],
          "criminal_complaints": []
        }
      ],
      "date_created": "2024-04-24T13:33:39.096780-07:00",
      "date_modified": "2024-04-24T13:33:39.096790-07:00",
      "name": "Samuel Jackson",
      "extra_info": ""
    },
    ...
  ]
}
```

Note that:

1. There are 35 parties in this case. (Only the first is shown in this example.)

2. The first party (ID 42) has had two attorneys. The first attorney (ID 1) represented them with role 10 in case 123 (the one we filtered to). The second attorney (ID 2) represented party 42 with role 2 in case 456.

3. The `party_types` field indicates the role the party has in the case (defendant, plaintiff, trustee, etc).

4. In criminal cases, the `party_type` field may also include the highest offenses, criminal counts, and criminal complaints against the defendant.

These endpoints are only available to select users. Please [get in touch][contact] to access these endpoints.

### Attorneys
`/api/rest/v4/attorneys/`

Use this API to look up an attorney in our system.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP OPTIONS request.

Like docket entries and parties, attorneys can be filtered to a particular docket. For example:

> [!WARNING]
> **Listen Up:** Like the parties endpoint, filters applied to this endpoint only affect the top-level data. To filter the nested data for each attorney, include the `filter_nested_results=True` parameter in your API request URL.

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/attorneys/?docket=4214664"
```

Returns:

```json
{
  "next": "https://www.courtlistener.com/api/rest/v4/attorneys/?docket=4214664&cursor=cD0xMjA5NjAyMg%3D%3D&docket=4214664",
  "previous": null,
  "results": [
    {
        "resource_uri": "https://www.courtlistener.com/api/rest/v4/attorneys/9247906/",
        "id": 9247906,
        "parties_represented": [
            {
                "role": 10,
                "docket": "https://www.courtlistener.com/api/rest/v4/dockets/4214664/",
                "party": "https://www.courtlistener.com/api/rest/v4/parties/13730908/",
                "date_action": null
            }
        ],
        "date_created": "2024-04-24T13:33:39.109264-07:00",
        "date_modified": "2024-05-07T21:32:12.465340-07:00",
        "name": "ERIC ALAN ISAACSON",
        "contact_raw": "6580 Avenida Mirola\nLa Jolla, CA 92037\n(858) 263-9581\nPRO SE\n",
        "phone": "(858) 263-9581",
        "fax": "",
        "email": ""
    },
    ...
  ]
}
```

Similar to the party API above, when you filter attorneys to a particular docket, the nested `parties_represented` field is not filtered and can show other parties the attorney represented in other dockets.

These endpoints are only available to select users. Please [get in touch][contact] to access these endpoints.

### Originating Court Info
`/api/rest/v4/originating-court-information/`

`Originating Court Information` represents the information gathered at an appellate court about a case when it was in a lower court or administrative body.

The information in this table is joined via a one-to-one relationship to the `Docket` object. Generally, this table is only completed for appellate cases that we acquire from PACER.

Cross-walking from the upper court docket to the lower is possible using the `docket_number` and `appeal_from` fields.

### Bankruptcy Information
`/api/rest/v4/bankruptcy-information/`

`Bankruptcy Information` represents metadata specific to PACER bankruptcy dockets, such as details about the bankruptcy case, including the chapter, trustee information, and key dates.

The information in this table is joined via a one-to-one relationship to the `Docket` object. Generally, it is only populated for dockets acquired from bankruptcy courts via PACER, so it does not apply to other types of cases.

### Integrated Database
`/api/rest/v4/fjc-integrated-database/`

`FJC Integrated Database` objects represent the information available in the [Federal Judicial Center's Integrated Database][fjc-idb], a regularly updated source of metadata about federal court cases. You can learn more about the IDB from the following sources:

- [The FJC IDB Homepage][fjc-idb]
- [Our datasheet on the IDB][idb-facts]
- The various codebooks for [civil][codebook-civil], [criminal][codebook-criminal], [appellate][codebook-appellate], and [bankruptcy][codebook-bankruptcy] datasets.

As always, you can find our interpretations of these fields by performing an `OPTIONS` request on this endpoint.

**Note:** Pending further support, this endpoint should be considered *experimental* quality. It is not guaranteed to have all of the available data sets, may not have the latest quarterly data, and indeed may have bugs. If you encounter any bugs, please let us know. If you would like better guarantees about the quality of this endpoint, we are enthusiastic about finding partners to better support it.

[fjc-idb]: https://www.fjc.gov/research/idb
[idb-facts]: https://free.law/idb-facts/
[codebook-civil]: https://www.fjc.gov/sites/default/files/idb/codebooks/Civil%20Codebook%201988%20Forward_0.pdf
[codebook-criminal]: https://www.fjc.gov/sites/default/files/idb/codebooks/Criminal%20Code%20Book%201996%20Forward.pdf
[codebook-appellate]: https://www.fjc.gov/sites/default/files/idb/codebooks/Appeals%20Codebook%202008%20Forward.pdf
[codebook-bankruptcy]: https://www.fjc.gov/sites/default/files/idb/codebooks/Bankruptcy%20Codebook%202008%20Forward%20(Rev%20January%202018).pdf

## Fast Document Lookup
`/api/rest/v4/recap-query/`

This API is used to check if documents with known IDs are available in our system.

To use it, provide a court ID and a comma-separated list of `pacer_doc_id`'s:

```
curl \
  --header 'Authorization: Token <your-token-here>' \
  'https://www.courtlistener.com/api/rest/v4/recap-query/?docket_entry__docket__court=dcd&pacer_doc_id__in=04505578698,04505578717'
```

This will return one entry for each document found, up to a maximum of 300 items:

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "pacer_doc_id": "04505578717",
      "filepath_local": "recap/gov.uscourts.dcd.178502/gov.uscourts.dcd.178502.2.0_54.pdf",
      "id": 2974081
    },
    {
      "pacer_doc_id": "04505578698",
      "filepath_local": "recap/gov.uscourts.dcd.178502/gov.uscourts.dcd.178502.1.0_48.pdf",
      "id": 2974077
    }
  ]
}
```

CourtListener court IDs match the subdomains on PACER, except for the following mapping:

| PACER Code | CL ID | Description |
|---|---|---|
| azb | arb | Arizona Bankruptcy Court |
| cofc | uscfc | Court of Federal Claims |
| neb | nebraskab | Nebraska Bankruptcy |
| nysb-mega | nysb | Do not use 'mega' |

> [!WARNING]
> **Careful:** When placing queries, the fourth digit of a PACER document ID can be a zero or one. We always normalize it to zero, and you will need to do so in your queries.

To query whether a case is in our system, use the `Docket` endpoint described above.

This endpoint is only available to select users. Please [get in touch][contact] to access this API.

[contact]: https://www.courtlistener.com/contact/
