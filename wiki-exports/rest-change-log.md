---
title: "REST API Change Log"
description: "A log of changes to the CourtListener REST API across all versions."
redirect_from: "/help/api/rest/changes/"
wiki_path: "/c/courtlistener/help/api/rest/change-log/"
---

**v4.4**
: Adds bankruptcy information support. This release introduces:
  - A new `bankruptcy_information` field in the [/dockets][pacer-dockets] endpoint that links to detailed bankruptcy metadata when available.
  - A new [/bankruptcy-information][pacer-bankruptcy] endpoint providing access to bankruptcy-specific data including chapter, trustee information, and key dates.

**v4.3**
: Enhances security by enforcing authentication in V4 API endpoints. Anonymous requests now receive a `401 Unauthorized` response. This change affects the following endpoints:
  - [/dockets][pacer-dockets]
  - [/opinion-clusters][cluster-endpoint]
  - [/opinions][opinion-endpoint]

**v4.2**
: Enhances support for [Field Selection][field-selection] in nested resources via the `fields` and `omit` parameters to reduce payload size and improve response times. Clients can now select nested fields (e.g. `fields=educations__date_modified`) or exclude them (e.g. `omit=recap_documents__plain_text`), allowing fine-grained control over serialized nested data. ([Issue #5748][issue-5748], [PR #5973][pr-5973])

**v4.1**
: This release introduces a number of enhancements aimed at improving the efficiency and flexibility of your data retrieval.
  - **Enhanced Paginated Endpoints:** Introduced the [count=on][counting] query parameter to efficiently retrieve total item counts without fetching actual data ([Issue #4506][issue-4506], [PR #4715][pr-4715]).
  - **Search Results:** Improved search results across all search types by incorporating [score values][search-notes] to the payload ([Issue #4312][issue-4312], [PR #4712][pr-4712]).
  - **Flexible Docket Entry Sorting:** The [Docket Entry endpoint][docket-entries] now supports sorting results by `recap_sequence_number` and `entry_number`. This added flexibility allows you to customize your data retrieval to meet specific requirements. ([Issue #4061][issue-4061], [PR #4700][pr-4700]).
  - **Deeper Filtering for Parties and Attorneys:** The [parties][parties] and [attorneys][attorneys] API endpoints has been upgraded with the `filter_nested_results=True` query parameter. This enables granular filtering of nested data, providing more control over the retrieved information. ([Issue #4054][issue-4054], [PR #4729][pr-4729]).
  - **Enhanced Court Filtering:** The `parent_court` query parameter has been added to the [Court endpoint][courts], allowing you to filter results based on parent-child relationships between courts. ([Issue #4711][issue-4711], [PR #4744][pr-4744]).

**v4.0**
: Migrate search to ElasticSearch and enable cursor-based pagination. See the [Migration Guide][migration-guide] for details.

**v3.15**
: Allow deep pagination on the Court endpoint, add `docket_id` to the Clusters endpoint, and add `cluster_id` and `author_id` to the Opinions endpoint.

**v3.14**
: This release blocks users from paginating past page 100 in the API. This release is not backwards incompatible, but is being released on an emergency basis to stop crawlers that have been impacting our database tier. In our performance documentation, we have long warned against using deep pagination. Now it is blocked. If you need this functionality for your application, please consider using filters to complete your crawling instead.

**v3.13**
: This version adds data from newly added judicial financial disclosure documents. This data is now included in a series of new endpoints to explore financial disclosures. For example, you can filter by gifts received by a specific federal judge or district.

  The new endpoints include `gifts`, `reimbursements`, `disclosure-positions`, `agreements`, `debts`, `investments`, `spouse-income`, `non-investment-incomes` and `financial-disclosures`. For an understanding of these fields, see the endpoint documentation.

**v3.12**
: This version deprecates the experimental Core API interface we tried previously. Swagger/OpenAPI has become the standard. Our support of OpenAPI remains experimental, but our toolkit should support it better than previously.

  Many endpoints can only be filtered by specific values. For example, to filter the `educations` endpoint to only bachelor's degrees, you'd use `degree_level=ba` as part of your GET request. In the past, if invalid filter values were used, zero results would be returned because zero items would match that query. This made sense, but did not help users identify their error. These values now return a `400` status code and an error message instead.

**v3.11**
: This version adds several fields and changes one.

  `Person.date_completed`: The date and time the person was last considered complete.

  `Person.dod_country` and `Person.dob_country`: The country where a person was born or died.

  `Position.sector`: Whether a position was in the private or public sector.

  `Court.date_last_pacer_contact`: This will track the last time we contacted PACER for a court.

  `Court.pacer_rss_entry_types`: This will track the types of entries available in a court's PACER RSS feed.

  `Position.date_started` is now a nullable field.

**v3.10**
: This version introduces the visualization APIs.

**v3.9**
: This version adds attachment page fetching to the RECAP fetch API.

**v3.8**
: This version adds fields to support Harvard case law data. This includes `correction`, `cross_reference`, `disposition`, `headnotes`, `history`, `other_dates` and `summary` fields for Cluster endpoint, and `joined_by_str` and `xml_harvard` fields for Opinion endpoint.

**v3.7**
: This version adds data from the Federal Judicial Center's Integrated Database. This data is now included in a new endpoint and as a new `idb_data` key in the Docket object. For an understanding of these fields, see the endpoint documentation.

**v3.6**
: This version deprecated the numerous `federal_cite_one`, `neutral_cite`, `lexis_cite`, and other citation fields, replacing them with a nested field called `citations`. The old fields will continue receiving updates until February 1, 2019, and will be removed on May 1, 2019.

**v3.5**
: This version adds the `mdl_status` field to the docket endpoint.

**v3.4**
: This version adds the `file_size` field to the RECAP document endpoint. This field contains the size (in bytes) of any document that we have.

**v3.3**
: This version added a variety of appellate fields to the docket object including a new related item called the `OriginalCourtInformation`. See the [Original Court endpoint documentation][orig-court-info].

  The new fields added to the docket include `appeal_from`, `appeal_from_str`, `originating_court_information`, `panel`, `panel_str`, `appellate_fee_status`, and `appellate_case_type_information`.

**v3.2**
: This version added the `id` field to many of the endpoints.

**v3.1**
: This version added experimental Swagger and Core API implementations.

**v3.0**
: Upgraded and overhauled the API to use the Django REST Framework.

**v2**
: [For original documentation, see: /help/api/rest/v2/][rest-v2]

**v1**
: [For original documentation, see: /help/api/rest/v1/][rest-v1]

[pacer-dockets]: pacer-api.md#dockets
[pacer-bankruptcy]: pacer-api.md#bankruptcy-information
[cluster-endpoint]: case-law-api.md#clusters
[opinion-endpoint]: case-law-api.md#opinions
[field-selection]: rest-api.md#field-selection
[issue-5748]: https://github.com/freelawproject/courtlistener/issues/5748
[pr-5973]: https://github.com/freelawproject/courtlistener/pull/5973
[counting]: rest-api.md#counting
[issue-4506]: https://github.com/freelawproject/courtlistener/issues/4506
[pr-4715]: https://github.com/freelawproject/courtlistener/pull/4715
[search-notes]: search-api.md#special-notes
[issue-4312]: https://github.com/freelawproject/courtlistener/issues/4312
[pr-4712]: https://github.com/freelawproject/courtlistener/pull/4712
[docket-entries]: pacer-api.md#docket-entries
[issue-4061]: https://github.com/freelawproject/courtlistener/issues/4061
[pr-4700]: https://github.com/freelawproject/courtlistener/pull/4700
[parties]: pacer-api.md#parties
[attorneys]: pacer-api.md#attorneys
[issue-4054]: https://github.com/freelawproject/courtlistener/issues/4054
[pr-4729]: https://github.com/freelawproject/courtlistener/pull/4729
[courts]: pacer-api.md#courts
[issue-4711]: https://github.com/freelawproject/courtlistener/issues/4711
[pr-4744]: https://github.com/freelawproject/courtlistener/pull/4744
[migration-guide]: migration-guide.md
[orig-court-info]: pacer-api.md#originating-court-info
[rest-v2]: https://www.courtlistener.com/help/api/rest/v2/
[rest-v1]: https://www.courtlistener.com/help/api/rest/v1/
