---
title: "REST API, v2"
description: "The first REST API for federal and state case law and still the best. Provided by Free Law Project, a 501(c)(3) non-profit."
redirect_from: "/help/api/rest/v2/overview/"
wiki_path: "/c/courtlistener/help/api/rest/v2/overview/"
search_engines: false
ai_assistants: false
---

> [!WARNING]
> **Deprecated** — These notes are for a version of the API that has been deprecated and will soon be disabled completely. Please use the [latest version][rest-api], as these notes are only maintained to help with migrations.


## General Notes

For developers that wish to have a more granular API for our data, we provide a RESTful API based on the [tastypie toolkit][tastypie].

This API currently has nine endpoints that can be consumed via GET requests:

1. [/api/rest/v2/docket/][api-v2-docket]
2. [/api/rest/v2/audio/][api-v2-audio]
3. [/api/rest/v2/document/][api-v2-document]
4. [/api/rest/v2/cites/][api-v2-cites]
5. [/api/rest/v2/cited-by/][api-v2-cited-by]
6. [/api/rest/v2/citation/][api-v2-citation]
7. [/api/rest/v2/jurisdiction/][api-v2-jurisdiction]
8. [/api/rest/v2/search/][api-v2-search]
9. [/api/rest/v2/coverage/all/][api-v2-coverage]

These endpoints can be used in combination to make sophisticated queries against our database or our search engine and are described in detail below. With the exception of the coverage endpoint, each of these have schema documents associated with them that can be found by appending "schema" to their location (e.g. [/api/rest/v2/document/schema/][api-v2-document-schema]).

The following representation of our database should be instructive when thinking about how these endpoints work together:

![Schema design diagram][schema-design]

(A more detailed version of this diagram [was posted to our developer mailing list][schema-detail].)

[schema-design]: https://www.courtlistener.com/static/png/schema-design.png
[schema-detail]: https://lists.freelawproject.org/pipermail/dev/2014-September/000084.html
[api-v2-docket]: https://www.courtlistener.com/api/rest/v2/docket/
[api-v2-audio]: https://www.courtlistener.com/api/rest/v2/audio/
[api-v2-document]: https://www.courtlistener.com/api/rest/v2/document/
[api-v2-cites]: https://www.courtlistener.com/api/rest/v2/cites/
[api-v2-cited-by]: https://www.courtlistener.com/api/rest/v2/cited-by/
[api-v2-citation]: https://www.courtlistener.com/api/rest/v2/citation/
[api-v2-jurisdiction]: https://www.courtlistener.com/api/rest/v2/jurisdiction/
[api-v2-search]: https://www.courtlistener.com/api/rest/v2/search/
[api-v2-coverage]: https://www.courtlistener.com/api/rest/v2/coverage/all/
[api-v2-document-schema]: https://www.courtlistener.com/api/rest/v2/document/schema/

The basic ideas are:

- Each Audio file and each Document are associated with a Docket, and each Docket can have many Documents or Audio files associated with it (sometimes thousands).
- Each Docket is associated with a single jurisdiction. Generally, this is the court where the dispute was litigated. If the case moves between jurisdictions, each jurisdiction has its own docket.
- Each Document, if it is an Opinion, has an associated Citation object.
- Different Documents cite different Citations, forming a many to many relationship (cases_cited).


### Overview of Endpoints

This section explains general principles of the API and rules that apply to all of our RESTful endpoints.


#### Authentication

With the exception of the coverage endpoint, all of the endpoints use either [HTTP Basic Authentication][basic-auth] or Django Session Authentication. To use the API, you must therefore either be logged into the CourtListener website (Session Authentication) or you must use your CourtListener credentials to set up HTTP Basic Authentication. Both of these authentication mechanisms protect your credentials on the wire via HTTPS.

To do HTTP Basic Authentication using cURL, you might do something like this:

```
curl --user "harvey:your-password" "https://www.courtlistener.com/api/rest/v2/document/"
```

You can also do it in your browser with a url like:

```
https://harvey:your-password@www.courtlistener.com/api/rest/v2/document/
```

But that's not normally necessary because most browsers will provide you with a popup if you need to authenticate using HTTP Basic Authentication.

Authentication is necessary so we can monitor usage of the system and so we can assist with any errors that may occur. Per our [privacy policy][privacy], we do not track your queries in the API, though we may collect statistical information for system monitoring.


#### Serialization Formats

With the exception of the coverage endpoint (which is only available as JSON), requests may be serialized as JSON, JSONP, or XML, with JSON as the default. The format you wish to receive may be requested via the HTTP `Accept` header or via the `format` GET parameter.

Note that because your browser prioritizes `application/xml` over `application/json`, you'll always receive XML when using your browser to explore our APIs. If you wish to override this, you may wish to use a less opinionated way of GETting resources such as cURL or you can override it using the `format` GET parameter, like so:

```
https://www.courtlistener.com/api/rest/v2/document/?format=json
```

If you wish to receive XML via a tool such as cURL, set the Accept header manually, like so:

```
curl -H "Accept: application/xml" https://www.courtlistener.com/api/rest/v2/document/
```

Or again, you can use the `format` GET parameter:

```
curl https://www.courtlistener.com/api/rest/v2/document/?format=xml
```


#### Views, Pagination and Subset Selection

Each endpoint provides a list view, a detail view and a set view. The *list* view is what you see when you visit an endpoint, when it shows a list of results. The *detail* view shows all meta data for a single result and can be viewed by following the `resource_uri` field for a result on the list view. Occasionally, content is excluded from the list view for performance reasons, but it may be available on the detail view. With the exception of the coverage API, links to the next and previous pages are available in the `meta` section of the results.

A subset of results may be selected by using the *set* view, and separating the IDs you wish to receive with semi-colons. For example this returns three jurisdictions using the `jurisdiction` endpoint:

```
curl "https://www.courtlistener.com/api/rest/v2/jurisdiction/set/scotus;ca9;cal"
```

Note that we use quotation marks in this query in order to escape shell interpretation of the semicolons.


#### Filtering

With the exception of the coverage endpoint, each endpoint can be filtered in various ways, as defined in their schema (available at `/api/rest/v2/$endpoint/schema/`). In the schemas you will find rules defining how each field can be filtered. These correspond to the [field lookups in the Django Queryset API][django-lookups]. If a field has `1` as its available rule, that indicates that *all* Django Queryset field lookups are available on that field.

Field lookups can be used by appending them to a field with a double underscore as a separator (examples are below in the documentation for various endpoints).


#### Ordering

With the exception of the coverage endpoint, ordering can be done on fields defined in the *ordering* section of an endpoint's schema. Ordering is done using the `order_by` GET parameter, with descending ordering available by prepending the minus sign (e.g. `order_by=-date_modified`). However, because the *search* endpoint uses Solr for its backend, ordering is instead done using the `asc` and `desc`, as described in detail below. This allows the URLs used for the search endpoint to match those used in front-end queries.


#### Field Selection

To save bandwidth and speed up your queries, fields can be limited by using the `fields` GET parameter with a comma-separated list of fields you wish to receive.

For example, if you wish to only receive the `resource_uri` and `absolute_url` fields from the `document` endpoint you could do so with:

```
curl https://www.courtlistener.com/api/rest/v2/document/?fields=absolute_url,resource_uri
```

Using the double underscore syntax, this can also be used for nested resources. For example, the `document` endpoint nests the `citation` endpoint in its results and the `citation` endpoint has a field called `federal_cite_one`. If you wished to use the `document` endpoint to only get back the nested `federal_cite_one` field, you could do so with:

```
curl https://www.courtlistener.com/api/rest/v2/document/?fields=citation__federal_cite_one
```

Using the `fields` parameter in these ways could save both of us time and bandwidth if you are making many requests. Please consider using this parameter for your requests.


#### Limitations

At present, this API is throttled to 1,000 queries per endpoint per user per hour, while we learn where our performance bottlenecks are. If you are hitting this limit or anticipate doing so, please get in touch so we can investigate easing your thresholds.

On the list view, 20 results are shown at a time by default. This can be limited to show fewer results, but cannot be set to show more. The `jurisdiction` endpoint allows up to 1,000 results at a time by setting the `limit` GET parameter like so:

```
curl https://www.courtlistener.com/api/rest/v2/jurisdiction/?limit=50
```


#### Date Formats

As [required by influential comic strips][xkcd-dates], all date formats are set to [ISO-8601 format][iso-8601].


#### The `absolute_url` Field

The `absolute_url` field shows the URL where a resource can be seen live on the site. It is absolute in the sense that it should never change and will always be backwards compatible if changes are ever needed (as in the upgrade to v2 of this API).

In some cases you might only have a URL, and you might want to look up the item in the API. `absolute_url`s generally look like this:

```
/$document-type/$numeric-id/$name-of-the-case/
```

There are three sections:

1. **$document-type**: This is the type of document that has been returned, for example, "opinion" indicates that you have gotten an opinion as your result.
2. **$numeric-id**: This is a numeric representation of the ID for the document. This value increments as we add content to the system. Note that due to deletions and modifications the numeric IDs are not guaranteed to be purely sequential — IDs will be missing.
3. **$name-of-the-case**: This is the "[slug][slug-wiki]" of the document, and generally mirrors its case name. This value can change if we clean up a case name, but provided it is not omitted completely, this part of the URL can be any value without ever affecting the page that is loaded. Put another way, we load pages based on the `$numeric-id` and `$document-type`, not by the name of the case.

[slug-wiki]: https://en.wikipedia.org/wiki/Slug_%28publishing%29


#### IDs and SHA1 Sums

Because of the way the data is organized in our backend, there is a unique ID for each citation and each document. This means that when you are working with the `citation` endpoint, you cannot use the document IDs, and vice versa. For example, this:

```
curl https://www.courtlistener.com/api/rest/v2/document/111170/
```

Returns *[Strickland v. Washington][strickland]*. But this does not:

```
curl https://www.courtlistener.com/api/rest/v2/citation/111170/
```

Even though they have the same ID. Each document and audio file also has a globally unique [SHA1][sha1] sum that can be queried using the search endpoint:

```
https://www.courtlistener.com/api/rest/v2/search/?q=a2daab35251795fc2621c6ac46b6031c95a4e0ba
```

To get audio results, also set the type parameter to `oa`, for oral arguments.

[strickland]: https://www.courtlistener.com/opinion/111170/strickland-v-washington/


#### Upgrades and Fixes

Like the rest of the CourtListener platform, this API and its documentation are [open source][cl-api-source]. If it lacks functionality that you desire or if you find [these notes][cl-api-templates] lacking, pull requests providing improvements are very welcome. Just get in touch in [our developer forum][dev-forum] to discuss your ideas or, if it's a quick thing, just go ahead and send us a pull request.

[cl-api-source]: https://github.com/freelawproject/courtlistener/tree/main/alert/search/api2.py
[cl-api-templates]: https://github.com/freelawproject/courtlistener/tree/main/alert/assets/templates/api
[dev-forum]: https://lists.freelawproject.org/cgi-bin/mailman/listinfo/dev


### /api/rest/v2/document/

This can be considered the main endpoint for many users. It provides access to the documents in our database and can be filtered or ordered in various ways as mentioned above. As with all endpoints, field descriptions can be found in the schema document. Visiting this endpoint provides the metadata for 20 documents at a time. The full text of the documents may be found by visiting their detail page, which can be found by following the `resource_uri` attribute for a result. Full text is not provided by default to save on bandwidth and processing.

The results at this endpoint can be filtered by a number of fields. Among others, this includes filtering by:

- `blocked`: Whether the document should be blocked from search engines.
- `citation_count`: The number of times the document has been cited by other documents.
- `court`: The ID of the court where the document was written.
- `date_filed`: The date the document was filed by the court.
- `date_modified`: The date and time the document was last modified.
- `extracted_by_ocr`: Whether the text of the document was extracted from an image using OCR.
- `precedential_status`: Whether the document has precedential value.
- `time_retrieved`: The date and time the document was added to our system.

For the full list of filtering fields, see the *filtering* section of the [schema document][api-v2-document-schema-json].

As mentioned above, in the schema document you will find that each filtering field provides a list of field lookups that are available to it. The following query provides an example of these lookups in use. Observe the following query, which gets all items that were modified after June 9th, 2013 (`__gt`), ordered by `date_modified` (ascending).

```
curl https://www.courtlistener.com/api/rest/v2/document/?date_modified__gt=2013-06-09+00:00Z&order_by=date_modified
```

And remember, to flip the ordering, you can use a minus sign in your ordering argument (`order_by=-date_modified`).

The results of this endpoint can also be ordered by `time_retrieved`, `date_modified`, `date_filed`, or `date_blocked`. Again, this is described in more detail in the schema.

[api-v2-document-schema-json]: https://www.courtlistener.com/api/rest/v2/document/schema/?format=json


### /api/rest/v2/audio/

The `audio` endpoint is modeled after the `document` endpoint and has very similar behavior, except instead of serving documents, it currently serves oral arguments and may later serve other similar audio files. As with the document endpoint, it can be filtered and ordered by various fields as described in its [schema document][api-v2-audio-schema].

Aside from these few notes, the `audio` endpoint should be very familiar and should have no surprises.

[api-v2-audio-schema]: https://www.courtlistener.com/api/rest/v2/audio/schema/?format=json


### /api/rest/v2/cites/ and /api/rest/v2/cited-by/

These endpoints provide interfaces into the citation graph that CourtListener provides between documents. `/cites/` provides a paginated display of the documents that a document *cites*, and `cited-by` provides a paginated display of the documents that cite a document. These can be thought of as compliments, though the results can be dramatically different. For example, a very important document, *[Strickland v. Washington][strickland-scotus]*, has been cited thousands of times (`cited-by`), however no document cites thousands of other documents (looking in the database, it appears the limit is around 400 authorities).

These endpoints only provide limited functionality. They cannot be filtered or ordered and they do not provide a detail or set view. To use these endpoints, provide the ID of the document you wish to analyze, like so:

```
curl https://www.courtlistener.com/api/rest/v2/cited-by/?id=111170
```

Or the reverse:

```
curl https://www.courtlistener.com/api/rest/v2/cites/?id=111170
```

The `id` parameter is required.

[strickland-scotus]: https://www.courtlistener.com/opinion/111170/strickland-v-washington/


### /api/rest/v2/citation/

This endpoint is integrated into the `document` endpoint and is also available individually. This endpoint provides each of the many citations that an opinion can have. Since opinions are often included in several written reporters, there are fields in this model for numerous [parallel citations][parallel-citations].

After several years reorganizing our schema, we currently categorize citations into the following types:

- Neutral (e.g. 2013 FL 1)
- Federal (e.g. 5 F. 55)
- State (e.g. Alabama Reports)
- Regional (e.g. Atlantic Reporter)
- Specialty (e.g. Lawyers' Edition)
- Old Supreme Court (e.g. 5 Black. 55)
- Lexis or West (e.g. 5 LEXIS 55, or 5 WL 55)

Some opinions have multiple citations of a given type, and to support those instances we provide several fields of that type. For example, we have fields for `federal_cite_one`, `federal_cite_two`, and `federal_cite_three`, which together can hold three parallel federal citations for a single opinion.

All of the filtering, ordering and field lookups described above can be used on this endpoint, as described in its [schema][api-v2-citation-schema]. This endpoint also provides a field called `opinion_uris`, which references the parent opinion for a citation.

At present, for performance reasons it is not possible to filter based on a citation. For this purpose, we recommend the [search endpoint](#apirestv2search). For instance, when you know a citation and want to see what information we have about it, try something like: <https://www.courtlistener.com/api/rest/v2/search/?citation=101%20U.S.%2099>.

[api-v2-citation-schema]: https://www.courtlistener.com/api/rest/v2/citation/schema/?format=json


### /api/rest/v2/jurisdiction/

This is the simplest of our REST endpoints and currently provides basic information about the hundreds of jurisdictions in the American court system that we support.

This endpoint can be filtered or ordered in numerous ways as described in its [schema][api-v2-jurisdiction-schema]. Brief descriptions of the fields can be found there as well.

Over time this endpoint will contain more and more information about jurisdictions such as the address of the courthouses and other such information. We welcome data contributions in this area as much of this information will need to be gathered manually.

[api-v2-jurisdiction-schema]: https://www.courtlistener.com/api/rest/v2/jurisdiction/schema/


### /api/rest/v2/search/

This endpoint allows you to query our search engine in a similar manner as is possible in our front end. Because this endpoint does not use the Django models directly, this endpoint is quite different than any other. Several differences should be noted.

First, the fields and results from this endpoint are slightly different than those in the other endpoints. For example, instead of using a minus sign to flip ordering, it uses `asc` and `desc`. And instead of the `court` field returning a reference to the `jurisdiction` endpoint, it provides the name of the jurisdiction where the document was issued. (See [the schema][api-v2-search-schema] and the notes below for all of the ordering options and field information).

A peculiarity of this endpoint is that, like the front end, it serves both `audio` and `document` results, depending on the value of the `type` argument. These results have many overlapping fields, so, for example, if you get back the field `download_url` and the `type` is set to the letter `o` (meaning opinions):

```
curl https://www.courtlistener.com/api/rest/v2/search/?type=o
```

...`download_url` will represent the location the opinion was downloaded from. Conversely, if `type` is set to the letters `oa` (meaning oral arguments), the `download_url` will represent the location the *audio file* was downloaded from, instead. This can be confusing, however, remember that the `type` field defaults to `o`, and that the fields that overlap should make sense for all result types.

Because this endpoint hits against a Solr search index instead of a database, the filtering works differently. To filter on this endpoint, we recommend identifying an effective query on the front end that generates the results you desire and then using that query (and variations thereof) to query the API. On the backend, the same code serves both the API and the front end.

When examining the *filtering* section of [the schema][api-v2-search-schema], note that fields have been labeled as follows:

**search**
: These fields are filterable according to the syntax defined in the [advanced query techniques][advanced-search] available on the front end.

**int**
: These fields require ints as their arguments, and generally provide greater-than or less-than queries.

**date**
: These fields allow you to search for dates greater than or less than a given value. Input dates ascribe to ISO-8601 format, however, partial dates are allowed, and will be interpreted appropriately. For example, placing "2012" in the `filed_after` parameter will assume you mean documents after "2012-01-01".

**Boolean**
: Only the stat_* field is currently available as boolean. This field is represented by checkboxes in the front end, and can be enabled by setting its value to "on". For example to include only Precedential documents, you might place a query like:

  ```
  curl https://www.courtlistener.com/api/rest/v2/search/?stat_Precedential=on
  ```

**CSV**
: The `court` field is currently available as a list of comma separated values (CSV). Thus, to request multiple courts, you can simply separate their IDs with a comma. For example to get all documents from the Supreme Court (`scotus`) and the Ninth Circuit of Appeals (`ca9`), you would make a query like:

  ```
  curl https://www.courtlistener.com/api/rest/v2/search/?court=scotus,ca9
  ```

  IDs for all jurisdictions are available at the [jurisdictions page][jurisdictions].

Finally, note that like the front end, when the `type` is set to `o` (the default), only precedential results are returned by default. See below for an example that also returns non-precedential results.

Four fields in the search results require special explanation:

**`resource_uri`**
: Because this endpoint is designed to help find documents, once you've found the ones you want, we provide a `resource_uri` that directs you back to the `document` endpoint, which has all of the best meta data. This is in contrast to any of the other endpoints, but follows the pattern of searching for results and selecting them to examine the details.

**`snippet`**
: This field contains the same values as are found on the front end, utilizing the HTML5 `<mark>` element to identify up to five matches in a document. If you wish to use the snippet but do not want highlighting, simply use CSS to give the `mark` element no styling, like a `span` element. This field only responds to arguments provided to the `q` parameter. If that parameter is not used, the `snippet` field will show the first 500 characters of the `text` field.

**`stat_*`**
: For this Boolean field, we provide opinionated default values. Because most searchers are not interested in non-precedential (unpublished) results, we leave them out by default. If you wish to receive these items, you must explicitly ask for them as you do on the front end. For example, this query returns both precedential (published) and non-precedential (unpublished) results:

  ```
  curl https://www.courtlistener.com/api/rest/v2/search/?stat_Precedential=on&stat_Non-Precedential=on
  ```

**`court`**
: This field provides the name of the jurisdiction where the document was issued. In other endpoints, this field directs you to the `jurisdiction` endpoint.

[api-v2-search-schema]: https://www.courtlistener.com/api/rest/v2/search/schema/?format=json


### /api/rest/v2/coverage/

Unlike the other endpoints in this API, the coverage endpoint is not based on the [tastypie API framework][tastypie]. As a result it is much simpler, only providing data in a very specific manner, serialized as JSON. In the future we expect to expand this API to provide faceting along additional fields, but at present it simply provides jurisdiction counts by year for any requested jurisdiction. This API does not require authentication and is what powers our live [coverage page][coverage].

To receive jurisdiction counts by year, simply provide the jurisdiction ID you wish to query or the special keyword, `all`, which returns counts for all jurisdictions. For example, this provides annual counts for the Ninth Circuit of Appeals (`ca9`):

```
curl https://www.courtlistener.com/api/rest/v2/coverage/ca9/
```

[coverage]: https://www.courtlistener.com/coverage/


## Available Jurisdictions

We currently have hundreds of jurisdictions that can be accessed with our APIs. Details about the jurisdictions that are available can be found [here][jurisdictions].


## Powered By

If you are interested, we have a variety of ["Powered By" logos][press-assets] available for your website or application. We appreciate a reference, but it's not required.

[press-assets]: https://free.law/press-assets/


## CiteGeist Scores

If you are interested in the CiteGeist score for each opinion, it is now available via our [bulk data API][bulk-data].


## Maintenance Schedule

We regularly perform bulk tasks on our servers and maintain [a public calendar][calendar] for tracking them. If you intend to do bulk crawling of our API, please be mindful of this schedule.


## Browser Tools

Several tools are available to help view JSON in your browser. If you are using Firefox, check out [JSONovitch][jsonovitch]. If you are using Chrome, check out [JSONView][jsonview].

[jsonovitch]: https://addons.mozilla.org/en-US/firefox/addon/jsonovich/
[jsonview]: https://chrome.google.com/webstore/detail/jsonview/chklaanhfefbnpoihckbnefhakgolnmc?hl=en


## Copyright

Our data is free of known copyright restrictions.

[![Public Domain Mark][cc-pd-img]][cc-pd]

[rest-api]: rest-api.md
[tastypie]: https://django-tastypie.readthedocs.org/en/latest/
[basic-auth]: https://en.wikipedia.org/wiki/Basic_access_authentication
[privacy]: https://www.courtlistener.com/terms/#privacy
[django-lookups]: https://docs.djangoproject.com/en/dev/ref/models/querysets/#field-lookups
[xkcd-dates]: https://xkcd.com/1179/
[iso-8601]: https://en.wikipedia.org/wiki/ISO_8601
[sha1]: https://en.wikipedia.org/wiki/SHA-1
[parallel-citations]: https://legalresearchprinciples.pbworks.com/w/page/16129937/Parallel%20Citations
[advanced-search]: https://www.courtlistener.com/help/search/
[jurisdictions]: https://www.courtlistener.com/help/api/jurisdictions/
[bulk-data]: https://www.courtlistener.com/help/api/bulk-data/
[calendar]: https://www.google.com/calendar/embed?src=michaeljaylissner.com_fvcq09gchprghkghqa69be5hl0@group.calendar.google.com&ctz=America/Los_Angeles
[cc-pd]: https://creativecommons.org/publicdomain/mark/1.0/
[cc-pd-img]: https://www.courtlistener.com/static/png/cc-pd.png
