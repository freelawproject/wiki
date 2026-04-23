---
title: "RECAP APIs for PACER Data"
description: "Use these APIs to download content from PACER and share it in the RECAP Archive of federal court cases and filings."
redirect_from: "/help/api/rest/v4/recap/"
wiki_path: "/c/courtlistener/help/api/rest/v4/recap/"
---

<p class="lead">Use these APIs to scrape PACER data and to upload data into CourtListener's database of federal court cases and filings.</p>

Once data is gathered by these APIs, our [PACER APIs and data model][pacer-api] can be used to retrieve dockets, entries, parties, and attorneys from our system.

The endpoints for RECAP are:

- `/api/rest/v4/recap-fetch/` — Use this API to scrape PACER data, including dockets, PDFs, and more.
- `/api/rest/v4/recap/` — Use this API to upload PACER data to CourtListener and to check on the progress of an upload.

[pacer-api]: pacer-api.md

## PACER Fetch
`/api/rest/v4/recap-fetch/`

Use this API to buy PACER content and add it to CourtListener so that it is available via our website, APIs, [webhooks][webhooks], and [replicated database][replication]. This is [a free API][free-api] to use, but it uses your PACER credentials to purchase and download PACER content. You'll still have to pay your PACER bill when it comes.

Because downloading content from PACER takes time, this API is asynchronous. After you send an HTTP `POST`, it immediately responds with an ID for the request and places the request in a queue to be downloaded by our scrapers. Most requests are completed within seconds.

As the request is processed, it will have a status code:

| Code | Description |
|---|---|
| 1 | Awaiting processing in queue |
| 2 | Item processed successfully |
| 3 | Item encountered an error while processing |
| 4 | Item is currently being processed |
| 5 | Item failed processing, but will be retried |
| 6 | Item failed validity tests during your POST |
| 7 | There was insufficient metadata to complete the task |

### Monitoring Your Request

To monitor your request, poll the API for your request, or use our [Fetch Webhook][fetch-webhook] to get immediate updates without polling.

We recommend using the webhook endpoint, since it reduces load on our servers.

[fetch-webhook]: webhooks.md#recap-fetch-events

### PACER Password Rotation Requirement

As of 2025, the federal judiciary requires that **all PACER accounts change their passwords every 180 days.** Because the RECAP Fetch API uses your PACER credentials to log in and retrieve documents, this policy affects all Fetch API users.

This means:

- You'll need to **update your PACER password at least once every 180 days**.
- If your password expires, the Fetch API will no longer be able to log in on your behalf until you update it.

To use this API without downtime during password change events, we recommend using two PACER accounts, and rotating between them in your code.

### Security of RECAP Fetch API

A security maxim is to never share your password. This API requires that you violate this maxim. Why should you do so, and how do we handle your password securely?

While we prefer not to have unhashed user passwords, PACER lacks any permissions-based or granular authentication system. This means that the only way we can act on your behalf is to have your credentials.

Once we have your password, we work to rid ourselves of it as quickly as possible. We do not store it in our database or logs at any time. Instead, we use it to immediately log into the PACER system. That gives us cookies for your account, which we store in our in-memory database with a one hour expiration period. As soon as we have the cookies, we throw away your username and password.

The result of this system is that we have your password until we have logged you in, and no longer. After that point, we only have a cache of your cookies for one hour.

> [!WARNING]
> **Listen Up!** This API gets content on your behalf using *your* access rights. This means that if you use this API to request a sealed item from PACER, we will go get it and add it to our system, just like you asked. **Do not do this**. If you do this accidentally, [please get in touch][contact] as soon as possible, so we can revert the error.

If you have questions about our approach, please see [our vulnerability reporting policy and bug bounty program][vuln-policy], where you'll find details on contacting us.

[webhooks]: webhooks.md
[replication]: https://www.courtlistener.com/help/api/replication/
[free-api]: https://free.law/2019/11/05/pacer-fetch-api
[contact]: https://www.courtlistener.com/contact/
[vuln-policy]: https://free.law/vulnerability-disclosure-policy/

### Known Issues

#### PACER login may fail with missing cookie error

Some users have experienced the following error when using the RECAP Fetch API to log in to PACER:

```
PacerLoginException: Did not get NextGenCSO cookie when attempting PACER login.
```

This issue appears to be related to recent changes in PACER's password requirements and how it handles multi-factor authentication (MFA).

If you encounter this error, temporarily disabling multi-factor authentication on your PACER account may resolve the issue and allow the RECAP Fetch to complete the login successfully.

### API Examples

#### Purchasing PDFs

1. Set `request_type` field to `2`, which indicates PDFs.

2. Set the `recap_document` field to the ID for the RECAP Document you wish to add to our system.

   To identify the `recap_document` ID, look up the RECAP Document in [our PACER API][pacer-api] and provide the CourtListener ID for the item.

An example of downloading a PDF by `recap_document` ID might be:

```
curl -X POST \
  --data 'request_type=2' \
  --data 'pacer_username=xxx' \
  --data 'pacer_password=yyy' \
  --data 'recap_document=112' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/recap-fetch/"
```

If you have a client code, you can provide it to the API with the `client_code` parameter.

If we do not have the `pacer_doc_id` for a particular `recap_document`, we will not be able to download it. If that's the case, you'll get an error message asking you to download the docket, which will get us the `pacer_doc_id` we need. Once that is completed you can retry your PDF purchase.

#### Scraping Attachment Pages

Attachment pages are the pages that you see in PACER after you click to download a document if a docket entry has attachments. These pages are free in PACER. Fetching attachment pages is done same as PDFs, above, but with `request_type` set to `3`.

#### Purchasing Dockets

Buying docket information is done similarly, but has a few additional options:

1. Provide the `request_type` of `1` for dockets.

2. Indicate the docket you want by either a CourtListener `docket` ID, a `docket_number`-`court` pair or a `pacer_case_id`-`court` pair (for district court dockets only):

   - `pacer_case_id` is the internal ID in the PACER system.
   - `docket_number` is the visible docket number humans use to refer to the case.
   - `court` is the CourtListener court ID.

     CourtListener court IDs match the subdomains on PACER, except for the following mapping:

     | PACER Code | CL ID | Description |
     |---|---|---|
     | azb | arb | Arizona Bankruptcy Court |
     | cofc | uscfc | Court of Federal Claims |
     | neb | nebraskab | Nebraska Bankruptcy |
     | nysb-mega | nysb | Do not use 'mega' |

3. As when buying dockets from PACER directly, you can choose to buy only some docket entries (available for district court dockets only), omit parties, do a date range query, etc. To see how to use these options map to the API, place an HTTP `OPTIONS` request.

For example, this request identifies a case by docket number and court:

```
curl -X POST \
  --data 'request_type=1' \
  --data 'pacer_username=xxx' \
  --data 'pacer_password=yyy' \
  --data 'docket_number=5:16-cv-00432' \
  --data 'court=okwd' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/recap-fetch/"
```

This is the same, but includes parties and counsel:

```
curl -X POST \
  --data 'request_type=1' \
  --data 'pacer_username=xxx' \
  --data 'pacer_password=yyy' \
  --data 'docket_number=5:16-cv-00432' \
  --data 'court=okwd' \
  --data 'show_parties_and_counsel=true' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/recap-fetch/"
```

Finally, this request updates an existing docket in CourtListener by its ID, but only gets the parties and counsel. Docket entries are excluded by requesting only ones from before 1980:

```
curl -X POST \
  --data 'request_type=1' \
  --data 'pacer_username=xxx' \
  --data 'pacer_password=yyy' \
  --data 'docket=5' \
  --data 'show_parties_and_counsel=true' \
  --data 'de_date_end=1980-01-01' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/recap-fetch/"
```

Sometimes, we get a PDF before we get a docket, making it impossible to know what case the PDF is associated with. We call these "orphan documents" because they do not have valid parent objects in our system.

Later, when we receive new or updated docket information, we have an opportunity to fix this problem by checking our system for orphan documents. When this happens, the orphans will automatically be associated with the new docket information, and the case will have PDFs linked to it.

## Pray and Pay API
`/api/rest/v4/prayers/`

Use the [Pray and Pay system][pray-and-pay] to monitor when PDFs are added to CourtListener. If a PACER document is not yet available in the RECAP Archive, you create a prayer for it via this API. Later, when another user purchases that document from PACER or the Fetch API, your prayer is "granted" and you are notified via webhook or email.

This API enables you to programmatically create and manage prayers, making it ideal for:

- **Automated monitoring** — Track when specific documents become available without manual checking.
- **Bulk document requests** — Request multiple documents of interest efficiently.
- **Workflow integration** — Integrate document availability notifications into your systems via [webhooks][pray-and-pay-webhooks].

To learn more about the Pray and Pay system itself, including how to fulfill prayers and contribute documents, see the help documentation:

[Pray and Pay Help](https://www.courtlistener.com/help/pray-and-pay/){button}

### Creating Prayers

To create a prayer, send an HTTP `POST` request with the `recap_document` ID of the document you want:

```
curl -X POST \
  --data 'recap_document=112' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/prayers/"
```

The response will contain the created prayer:

```json
{
  "id": 12345,
  "date_created": "2025-01-15T10:30:00.123456-07:00",
  "status": 1,
  "recap_document": 112
}
```

The `status` field indicates whether the prayer is waiting (1) or has been granted (2). Newly created prayers always have status 1.

To identify the `recap_document` ID, look up the RECAP Document in [our PACER API][pacer-api] and provide the CourtListener ID for the item.

### Listing Your Prayers

To retrieve a list of your active (waiting) prayers, send an HTTP `GET` request:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/prayers/"
```

This returns only prayers with status 1 (WAITING). Once a prayer is granted (status 2), it will no longer appear in this list.

### Deleting Prayers

To delete a prayer before it is granted, send an HTTP `DELETE` request:

```
curl -X DELETE \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/prayers/12345/"
```

Note that prayers cannot be modified once created. The API does not support `PUT` or `PATCH` requests. If you need to change a prayer, delete it and create a new one.

### Webhook Notifications

When a prayer is granted and the document becomes available, you can be notified immediately via webhooks. This is the recommended way to monitor your prayers instead of polling the API.

Webhook events are sent as soon as a document becomes available and include the prayer ID, document ID, and status information. To set up webhook notifications for granted prayers, see the webhook documentation:

[Pray and Pay Webhooks](https://www.courtlistener.com/help/api/webhooks/#pray-and-pay){button}

### Limitations and Future Plans

The Pray and Pay API has the same limitations as the web interface:

- Standard users can create a limited number of prayers per day (the same daily quota applies to both web and API usage).
- Free Law Project members have a higher daily prayer limit.
- Prayers cannot be modified once created; they can only be created or deleted.
- Many documents may be unavailable for purchase on PACER (sealed filings, delayed transcripts, etc.). After you create a prayer, our system checks PACER availability. If unavailable, you'll receive an email notification.
- Once a prayer is granted (the document becomes available), it cannot be deleted.

In the future, we may allow higher prayer limits on a per-account basis for API users who need to monitor hundreds of documents programmatically. If your organization has this need, please [get in touch][contact] to discuss options.

[pray-and-pay]: https://www.courtlistener.com/help/pray-and-pay/
[pray-and-pay-webhooks]: webhooks.md#pray-and-pay-events

## RECAP Upload API
`/api/rest/v4/recap/`

This API is used by the RECAP extension and a handful of special partners to upload PACER content to the RECAP Archive. This API is not available to the public. If you have a collection of PACER data you wish to donate to the RECAP Archive so it is permanently available to the public, please [get in touch][contact].

We describe the process for completing these uploads below, and you can see examples of them in [CourtListener's automated test suite][recap-tests]. Uploads to these endpoints should be done using HTTP `POST` requests and multipart form data.

When you make an upload, you create a `Processing Queue` object in the CourtListener system. This object will be returned in the HTTP response to your upload, so you will know its ID. This object will contain the fields you uploaded, and the following fields will be populated as the item is processed:

| Field | Description |
|---|---|
| `status` | When you upload an item, it is placed into a queue until processing resources are available to merge it into the RECAP Archive. Use this field to determine where in that process your item is. To see the possible values, place an `OPTIONS` request to this endpoint. |
| `error_message` | This field will provide you information about whether your upload was processed successfully or will explain any errors that occurred. (It's not strictly errors.) |
| `docket` / `docket_entry` / `recap_document` | After an item is successfully processed, these fields will be populated with the IDs of the items that were created or updated. The `docket` field will be populated for dockets that were created or updated, and all three fields will be populated for uploaded PDFs. |

### Global Parameters

The following parameters apply to all uploads:

- `upload_type` *(required)* — This field accepts integers representing object types in PACER. Send an HTTP `OPTIONS` request to this API to learn the possible values for this field.
- `filepath_local` *(required)* — Use this field to upload the binary data you are submitting, whether it HTML of a docket or attachment menu or a PDF file.
- `court` *(required)* — The CourtListener court id.

  CourtListener court IDs match the subdomains on PACER, except for the following mapping:

  | PACER Code | CL ID | Description |
  |---|---|---|
  | azb | arb | Arizona Bankruptcy Court |
  | cofc | uscfc | Court of Federal Claims |
  | neb | nebraskab | Nebraska Bankruptcy |
  | nysb-mega | nysb | Do not use 'mega' |

- `debug` *(optional)* — While you are developing, use this field to test your work. When it is set to `true`, your uploads will not make changes to the RECAP Archive, but you will create processing requests which will be processed in debug mode.

### Uploading Dockets, History Reports, and Claims Registries

These are fairly straightforward uploads. In addition to the required fields above, supply the `pacer_case_id` field.

### Uploading PDFs

To upload PDFs, include the `pacer_doc_id` and `document_number` fields. For documents originating from courts outside the new Appellate Case Management System (ACMS), the fourth digit of the `pacer_doc_id` must always be normalized to a zero before uploading (see below).

If you are uploading an attachment, you must also provide the `attachment_number` field. Note that if you are not uploading an attachment, no `attachment_number` should be provided, otherwise the document will be marked as an attachment.

Because some cases share documents, the `pacer_case_id` field should also be provided, though it's not a required field if it's unknown.

`pacer_doc_id` is the number you see in URLs when purchasing documents on PACER and in the HTML when clicking document numbers on docket pages. For example, in the URL `ecf.flp.uscourts.gov/doc1/035021404350`, the `pacer_doc_id` is `035021404350`.

`pacer_doc_id` numbers, excluding those associated with ACMS, all share a common structure: they embed three variables within their format.

- The first three digits (in this case, `035`) are a code indicating the court.
- The fourth digit is a zero or one, and is a boolean value that determines if URL should load an attachment page for the document or instead take you directly to the purchase page (we believe this digit is why the URL mentions `/doc1/`).

  **Important:** When uploading to this endpoint, the fourth digit must always be normalized to a zero before uploading.
- The remaining digits are the serial number of the document itself.

When uploading documents from a court that uses ACMS, you'll notice the `pacer_doc_id` for attachments is identical across all records within the same entry. To ensure proper uploads, you must include the `acms_document_guid` for each document originating from this system.

Locating the `acms_document_guid` requires an additional step as its value is stored within the browser's `sessionStorage` object, accessible on the download page. The following script, executed in your browser's console, will help you retrieve this value:

```javascript
let downloadData =
  document.getElementsByClassName('text-center')[0].parentElement.__vue__._data;
  console.log(downloadData.docketEntryDocuments[0].docketDocumentDetailsId);
```

PDF uploads will only succeed when they can be associated with a docket. If the RECAP Archive does not have a docket for the `pacer_doc_id` you uploaded, your upload will be re-queued and retried several times. If that fails, your PDF upload will be marked as an "orphan document." Later, when the docket is uploaded, your PDF will be automatically associated with it. Until then it's not visible in the system.

### Uploading Document Zips

From the attachment page in district court PACER websites, there is a button to get all the documents for a particular docket entry as a zip. Such zips can be uploaded using the same parameters as PDFs, using the `upload_type` of `10`.

### Uploading Attachment Pages

These are the HTML pages that you will see that list the attachments for a docket entry. The only required field for this upload type is `pacer_case_id`.

### A Complete Example

Pulling this all together, a docket upload might look like:

```
curl -v \
  --form upload_type=1 \
  --form "filepath_local=@docket.html" \
  --form court=dcd \
  --form pacer_case_id=<some-value> \
  --form debug=true \
  'https://www.courtlistener.com/api/rest/v4/recap/'
  --header 'Authorization: Token <your-token-here>'
```

In response, you would receive an object like this:

```json
{
  "id": 13684105,
  "court": "dcd",
  "docket": null,
  "docket_entry": null,
  "recap_document": null,
  "date_created": "2024-05-18T08:01:14.457637-07:00",
  "date_modified": "2024-05-18T08:01:14.953939-07:00",
  "pacer_case_id": "",
  "pacer_doc_id": "",
  "acms_document_guid": "",
  "document_number": null,
  "attachment_number": null,
  "status": 1,
  "upload_type": 1,
  "error_message": "",
  "debug": false
}
```

Then, to check the status, you can poll it with:

```
curl \
  'https://www.courtlistener.com/api/rest/v4/recap/13684105/'
  --header 'Authorization: Token <your-token-here>'
```

Which will soon return:

```json
{
  "id": 13684105,
  "court": "dcd",
  "docket": "https://www.courtlistener.com/api/rest/v4/dockets/8903924/",
  "docket_entry": null,
  "recap_document": null,
  "date_created": "2024-05-18T08:01:14.457637-07:00",
  "date_modified": "2024-05-18T08:01:14.953939-07:00",
  "pacer_case_id": "",
  "pacer_doc_id": "",
  "acms_document_guid": "",
  "document_number": null,
  "attachment_number": null,
  "status": 2,
  "upload_type": 1,
  "error_message": "Successful upload! Nice work.",
  "debug": false
}
```

Note that:

- The `error_message` and `docket` fields are completed.
- The `status` field is now `2`.

[recap-tests]: https://github.com/freelawproject/courtlistener/blob/main/cl/recap/tests/tests.py
[pacer-api]: pacer-api.md
