---
title: "Oral Argument Recordings APIs"
description: "We have the biggest collection of oral argument audio in the world. Use these APIs to gather and analyze oral argument audio files from federal courts."
redirect_from: "/help/api/rest/v4/oral-arguments/"
wiki_path: "/c/courtlistener/help/api/rest/v4/oral-arguments/"
---

<p class="lead">Use these APIs to gather and analyze the largest collection of oral argument recordings on the Internet.</p>

## The APIs

### Oral Argument Recordings
`/api/rest/v4/audio/`

Use this API to gather data about oral argument recordings. This API is linked to the docket API (below), which contains data about each case. It is also linked to the [judge API][judge-api], which has information about the judges in the case.

The audio files we gather from court websites come in many formats. After we gather the files, we convert them into optimized MP3s that have a 22050Hz sample rate and 48k bitrate. After converting the files, we set the ID3 tags to better values that we scraped. Finally, we set the cover art for the MP3 to the seal of the court, and set the publisher album art to our logo.

The original audio files can be downloaded from the court using the `download_url` field. If you prefer to download our enhanced version, that location is in the `local_path_mp3` field. To download the file, see our [help article on this topic][field-help].

The `duration` field contains an estimated length of the audio file, in seconds. Because these MP3s are variable bitrate, this field is based on sampling the file and is not always accurate.

As with all other APIs, you can look up the field descriptions, filtering, ordering, and rendering options by making an `OPTIONS` request:

```
curl -v \
  -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/audio/"
```

[judge-api]: judge-api.md
[field-help]: field-help.md

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
