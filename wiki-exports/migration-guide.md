---
title: "V4 API Migration Guide"
description: "Guide for migrating from v3 to v4 of the CourtListener REST API."
redirect_from: "/help/api/rest/v4/migration-guide/"
wiki_path: "/c/courtlistener/help/api/rest/v4/migration-guide/"
---

After several years of planning and development, we have released v4 of our APIs.

This upgrade responds to feedback we have received over the years and should be much better for our users — faster, more featureful, more scalable, and more accurate.

Unfortunately, we couldn't make these new APIs completely backwards compatible, so this guide explains what's new.

## Support

Questions about this migration can be sent [to our GitHub Discussions forum][gh-discussions] or to our [contact form][contact].

We prefer that questions be posted in the forum so they can help others. If you are a private organization posting to that forum, we will avoid sharing details about your organization.

[Ask in GitHub Discussions](https://github.com/freelawproject/courtlistener/discussions){button} [Send us a Private Message](https://www.courtlistener.com/contact/){button}

## Timeline for Changes

v4 of the API is available now and is the default version for anybody creating new systems. Before its full release, a number of organizations beta tested it.

All of our APIs except for our search API are powered by our database. We do not have plans at present to deprecate any of these APIs, but we'd like to remove them someday and urge you to migrate to v4 as soon as possible so we can do that.

That said, the v3 Search API is currently powered by Solr while v4 is powered by ElasticSearch. In **nine weeks** we aim to switch v3 so it uses ElasticSearch too. This will change v3 in small backwards incompatible ways, but will allow us to continue supporting it even after turning off our Solr server.

If you are a v3 Search API user, you will soon get an email from us to communicate and discuss timelines.

## What If I Do Nothing?

You might be fine. Most of the database and search APIs are only changing slightly, and v3 will be supported for some period of time. But you should read this guide to see if any changes are needed to your application.

The remainder of this guide is in three sections:

- New features you can expect
- How to migrate database APIs
- How to migrate search APIs

We're very excited to be releasing v4 of our APIs. We hope you will review these changes so we can all have a smooth transition.

## What New Features Can I Expect?

### Cursor-Based Pagination

Our database-powered APIs now support cursor-based pagination. This allows you to crawl very deeply in the API. In v3, any page past 100 was blocked.

### ElasticSearch

v4 of the Search API is powered by ElasticSearch instead of Solr. This is a huge upgrade to our API and search engine.

Some improvements include:

- In v4, all PACER cases are now searchable. In v3 you only got results if a case had a docket entry.
- You can search for PACER filings based on what decisions they cite.
- You can now search for exact words like "Deposit" and not get back results for things like "Deposition."
- We've added about 800 legal acronyms like "IRS" to make sure those bring back results.
- Better relevancy for edge cases:
  - Small words like "of," "to," and "the" are now searchable.
  - Camelcase words like "McDonalds" are more searchable.
  - Highlighting is more consistent and can be disabled for better performance.
- Emojis and Unicode characters are now searchable.
- Docket number and other fielded searches are more robust.
- Timezone handling is more consistent.
- We've added a number of new searchable fields.

For more details, please [see our blog][blog-recap-search].

## Breaking Changes to v3 of the Search API

We cannot continue running Solr forever, but we can do our best to support v3 of the API. To do this, on **November 25, 2024**, v3 of the Search API will be upgraded to use ElasticSearch. We expect this to support most uses, but it will cause some breaking changes, as outlined in this section.

We recommend all users upgrade to v4 of the API, but if that is not possible, please review this section to learn about the upcoming changes to v3 of the search API.

### RECAP (type=r)

- The following fields will be removed from the v3 search API when `type=r`:
  - attorney
  - attorney_id
  - firm
  - firm_id
  - party
  - party_id
  - docket_absolute_url

- Fielded text queries that include party fields won't work, for instance:

  `firm_id:1245 AND party:(United States)`

- The `type=r` will use a cardinality aggregation to compute the result count, which will have an error of +/-6% if results are over 2000.

### Opinions (type=o)

- The following fields will be removed from the v3 search API when `type=o`:
  - caseNameShort
  - pagerank
  - status_exact
  - non_participating_judge_ids
  - source
- The `date_created` field will be added.
- The `snippet` will change. In the Solr version, it includes content from all fields, while in ElasticSearch it will display only the Opinion text content.
- The `type=o` will use a cardinality aggregation to compute the result count, which will have an error of +/-6% if results are over 2000 hits.

### Oral Arguments (type=oa)

- The `snippet` field currently stores a variety of fields. After the change, it will contain the audio transcription only.

### People (type=p)

- No breaking changes. v3 is already switched to ElasticSearch.

## How Do I Migrate Database APIs to v4?

### Result Count is Removed

The total count of the results is no longer available in the response. Most users don't need this when using the API, and computing the count for each response slows down the API. If this value is important to your service, let us know so we can discuss adding a new API with this feature.

### Invalid Cursor Error Code: 404

A new type of error in the v4 API is **Invalid Cursor** with a 404 status code.

This can happen when GET parameters are changed without getting a fresh cursor parameter. To prevent this error, do not change the GET parameters while maintaining an existing cursor parameter.

## Enhancements in Search API v4

### Search API Crawls Are No Longer Limited to 100 Pages

- Deep pagination of search results is now possible.
- Users cannot directly jump to a specific page. Look at and follow the `next` and `previous` parameters provided in each response. Navigation of the API is exclusively through those keys in each API response.

### Result Sorting is More Consistent

- When sorting the API results, we now add a tie-breaking field to all responses. This ensures that ordering is consistent even when the ordering key has identical values for multiple results.
- If your sorting field has null values, those results will be sorted at the end of the query, regardless of whether you sort in ascending or descending order. For example if you sort by a date that is null for an opinion, that opinion will go at the end of the result set.

### Highlighting is More Consistent

- When enabled, highlighting will more consistently highlight the fields in the response.

### Empty Fields Are Standardized

- Empty fields are now more consistent in their response types, and follow the conventions provided by Django. This means that dates, date times, and integers return `null`, strings return an empty string, and lists return an empty array.

## Backwards Incompatible Changes in Search API v4

### High Query Counts Are Estimated

- To enhance performance, query counts above 2,000 hits are approximate. For queries exceeding this threshold, counts can be off by as much as six percent. We recommend noting this in your interface by saying something like, "About 5,000 results," instead of presenting the value as exact.

### Highlighting

- To enhance performance, results are not highlighted by default. To enable highlighting, include `highlight=on` in your request.
- When highlighting is disabled, the first 500 characters of `snippet` fields are returned for types `o`, `r`, and `rd`.

### Nested Keys (Documents) for `type=o` and `type=p`

- To enhance the structure of the API, sub-opinions are now nested within clusters in case law results (`type=o`), and `positions` are nested within judges in judge results (`type=p`).

### `type=r` is Now For Dockets With Nested Documents

- To align the API results with the front end results, `type=r` no longer returns a flat list of documents. Instead, it now returns a list of dockets with up to three matching documents nested within each docket's `recap_documents` key.
- To return a flat list of documents, as in the past, try the new `type=rd` parameter. This can be useful for those upgrading from v3 to v4 of the search API.
- If there are more than three matching documents, the `more_docs` field for the docket result will be true. As in the front end, you can get the remaining documents for a docket by placing a docket ID query like: `type=rd&q=(original query) AND docket_id:XYZ`
- This response type includes two counts of the results: `count` is the number of dockets returned. `document_count` is the number of documents.

### `type=rd` is a New Result Type For Documents

- `type=rd` returns a flat list of PACER documents, and is similar to `type=r` in v3 of the API. Results for this type can be queried by any docket fields except the `party` and `attorney` fields.
- The field differences between `r` in v3 and `rd` in v4 are that all the docket-level fields were removed:
  - assignedTo
  - assigned_to_id
  - caseName
  - cause
  - court
  - court_citation_string
  - court_exact
  - court_id
  - dateArgued
  - dateFiled
  - dateTerminated
  - docketNumber
  - jurisdictionType
  - juryDemand
  - referredTo
  - referred_to_id
  - suitNature
- `docket_id` is still available in the `rd` type so users can identify the docket and pull additional docket data from the docket API.
- One field that changed is `entry_date_filed`. In `r` v3, it was a `datetime` field with PST midnight as the default time. Now, it's simply a date field.
- The `timestamp` field has been moved to the new `meta` field, which also contains `date_created`.

### `type=d` Still Returns Dockets

- `type=d` returns dockets without nested documents. If all you need in the response is the docket information, this response type will be significantly faster. You can query document fields with this response type even though they will not be returned.

### Removed Fields

- The following fields have been removed from the case law search results (`type=o`):
  - caseNameShort
  - pagerank
  - status_exact
  - non_participating_judge_ids

### Changed Field Values

- For legibility, in the case law search results (`type=o`), some `type` field values have changed:
  - 010combined -> combined-opinion
  - 015unamimous -> unanimous-opinion
  - 020lead -> lead-opinion
  - 025plurality -> plurality-opinion
  - 030concurrence -> concurrence-opinion
  - 035concurrenceinpart -> in-part-opinion
  - 040dissent -> dissent
  - 050addendum -> addendum
  - 060remittitur -> remittitur
  - 070rehearing -> rehearing
  - 080onthemerits -> on-the-merits
  - 090onmotiontostrike -> on-motion-to-strike

- Some of the values of the `status` field in the case law search results have changed:
  - precedential -> published
  - non-precedential -> unpublished
  - errata -> errata
  - separate opinion -> separate
  - in-chambers -> in-chambers
  - relating-to orders -> relating-to
  - unknown status -> unknown

- The `snippet` field in the case law search results previously included more than one opinion text field. It now only contains the best text field, based on the following priority and determined by availability:
  - html_columbia
  - html_lawbox
  - xml_harvard
  - html_anon_2020
  - html
  - plain_text

### Dates and Times

- All dates and times are in UTC instead of PST.
- Date objects are now rendered as an ISO-8601 date instead of an ISO-8601 datetime.

The following is a full list of date fields that are now date objects (rather than datetime objects, which they were in v3):

- types `r` and `d`:
  - dateArgued
  - dateFiled
  - dateTerminated

- types `r` and `rd`:
  - `entry_date_filed` (in type `r` is available in documents nested within the `recap_documents` key)

- type `o`:
  - dateArgued
  - dateFiled
  - dateReargued
  - dateReargumentDenied

- type `oa`:
  - dateArgued
  - dateReargued
  - dateReargumentDenied

- type `p`:
  - dob
  - dod
  - The following fields are available within the nested `positions` key:
    - date_confirmation
    - date_elected
    - date_hearing
    - date_judicial_committee_action
    - date_nominated
    - date_recess_appointment
    - date_referred_to_judicial_committee
    - date_retirement
    - date_start
    - date_termination

### No More Random Sorting

- You can no longer sort the results randomly. This was only used by developers and was difficult to support.

### Stemming and Synonyms

- To provide better relevancy, stemming and synonyms are disabled on the `caseName` fields.
- This is because broadening a query to include synonyms and other words with the same stem are not relevant when a user searches for a case by name. For example, when searching for a case name that includes the word "Howells" results for a search on the word "Howell" would not be relevant.
- This change applies to both the `case_name` filter and the text query.

### Changes to GET Parameters

- When searching the case law status fields, the GET parameters have been changed as follows:
  - stat_Precedential -> stat_Published
  - stat_Non-Precedential -> stat_Unpublished
  - stat_Errata -> stat_Errata
  - stat_Separate Opinion -> stat_Separate
  - stat_In-chambers -> stat_In-chambers
  - stat_Relating-to orders -> stat_Relating-to
  - stat_Unknown Status -> stat_Unknown

### Bad Request Error Code: 400

- The error can contain one of the following custom messages in the `detail` key, explaining the reason for the error:
  - The query contains unbalanced parentheses.
  - The query contains unbalanced quotes.
  - The query contains an unrecognized proximity token.

### Server Error Code: 500

- Any other error, such as a connection error or a parsing error of the ElasticSearch query, will raise `Server Error` Code: `500`.
- And the message in the detail key: `Internal Server Error. Please try again later or review your query.`

### Not Found Error Code: 404

- In the v4 Search API or other v4 database-based endpoints using cursor pagination, the following error can be raised: `Not Found Error` Code: `404`
- Message in the `detail` key: `Invalid cursor`
- This can happen if the cursor was modified manually or if the ordering key changed and doesn't match the ordering key in the cursor.
- To avoid this problem, when changing the sorting key, restart your request by removing the cursor key from your request.

[gh-discussions]: https://github.com/freelawproject/courtlistener/discussions
[contact]: https://www.courtlistener.com/contact/
[blog-recap-search]: https://free.law/2024/01/18/new-recap-archive-search-is-live/
