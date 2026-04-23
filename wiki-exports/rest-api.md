---
title: "REST API, v4.4"
description: "REST API for federal and state case law, PACER data, the searchable RECAP Archive, oral argument recordings and more."
redirect_from: "/help/api/rest/v4/overview/"
wiki_path: "/c/courtlistener/help/api/rest/v4/overview/"
data_source: "https://www.courtlistener.com/api/rest/v4/wiki-data/"
data_source_cache: 86400
---

<p class="lead">APIs for developers and researchers that need granular legal data.</p>

After more than a decade of development, these APIs are powerful. Our [case law API][case-law-api] was the first. Our [PACER][pacer-api] and [oral argument][oral-argument-api] APIs are the biggest. Our [webhooks][webhooks-getting-started] push data to you. Our [citation lookup tool][citation-lookup-api] can fight hallucinations in AI tools.

Let's get started. To see and browse all the API URLs, click the button below:

[Show the APIs](https://www.courtlistener.com/api/rest/v4/){button}

We could have also pulled up that same information using curl, with a command like:

```
curl "https://www.courtlistener.com/api/rest/v4/overview/"
```

Note that when you press the button in your browser, you get an HTML result, but when you run `curl` you get a JSON object. This is [discussed in more depth below](#serialization-formats).

> [!WARNING]
> **Listen Up!** Something else that's curious just happened. You didn't authenticate to the API. To encourage experimentation, many of our APIs are open by default. The biggest gotcha people have is that they forget to enable authentication before deploying their code. Don't make this mistake! Remember to add [authentication](#authentication).

The APIs listed in this response can be used to make queries against our database or search engine.

To learn more about an API, you can send an [HTTP OPTIONS][http-options] request, like so:

```
curl -X OPTIONS "https://www.courtlistener.com/api/rest/v4/overview/"
```

An `OPTIONS` request is one of the best ways to understand the API.

[case-law-api]: case-law-api.md
[pacer-api]: pacer-api.md
[oral-argument-api]: oral-argument-api.md
[webhooks-getting-started]: webhooks-getting-started.md
[citation-lookup-api]: citation-lookup-api.md
[http-options]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/OPTIONS


## Support

Questions about the APIs can be sent [to our GitHub Discussions forum][gh-discussions] or via our [contact form][contact].

We prefer that questions be posted in the forum so they can help others. If you are a private organization posting to that forum, we will avoid sharing details about your organization.

[Ask in GitHub Discussions](https://github.com/freelawproject/courtlistener/discussions){button}
[Send us a Private Message](https://www.courtlistener.com/contact/){button}

[gh-discussions]: https://github.com/freelawproject/courtlistener/discussions
[contact]: https://www.courtlistener.com/contact/


## Data Models

The two images below show how the APIs work together. The first image shows the models we use for people, and the second shows the models we use for documents and metadata about them. You can see that these models currently link together on the Docket, Person, and Court tables. ([Here's a version of this diagram that shows everything all at once][complete-model].)

[![People model schema diagram][people-model-small]][people-model]

[![Search model schema diagram][search-model-small]][search-model]

[complete-model]: https://www.courtlistener.com/static/png/complete-model-v3.13.png
[people-model-small]: https://www.courtlistener.com/static/png/people-model-v3.13-small.png
[people-model]: https://www.courtlistener.com/static/png/people-model-v3.13.png
[search-model-small]: https://www.courtlistener.com/static/png/search-model-v3.13-small.png
[search-model]: https://www.courtlistener.com/static/png/search-model-v3.13.png


## API Overview

This section explains the general principles of the API. These principals are driven by the features supported by the [Django REST Framework][drf]. To go deep on any of these sections, we encourage you to check out the documentation there.

[drf]: https://www.django-rest-framework.org/


### Permissions

Some of our APIs are only available to select users. If you need greater access to these APIs, [please get in touch][contact].

All other endpoints are available according to the [throttling](#rate-limits) and [authentication](#authentication) limitations listed below.


### Your Authorization Token

[Sign In To See Your Token](https://www.courtlistener.com/sign-in/){button}


### Authentication

Authentication is necessary to monitor and throttle the system, and so we can assist with any errors that may occur.

Per our [privacy policy][privacy-policy], we do not track your queries in the API, though we do collect statistical information for system monitoring.

There are currently three types of authentication available on the API:

1. [HTTP Token Authentication][token-auth]
2. [Cookie/Session Authentication][cookie-auth]
3. [HTTP Basic Authentication][basic-auth]

All of these methods are secure, so the choice of which to use is generally a question of what's most convenient for the context of your work. Our recommendations are:

- Use Token Authentication for programmatic API access.
- Use Cookie/Session Authentication if you already have a user's cookie or are developing a system where you can ask the user to log into CourtListener.
- Use Basic Authentication if that's all your client supports.

[privacy-policy]: https://www.courtlistener.com/terms/#privacy
[token-auth]: https://www.django-rest-framework.org/api-guide/authentication/#tokenauthentication
[cookie-auth]: https://docs.djangoproject.com/en/dev/topics/auth/
[basic-auth]: https://en.wikipedia.org/wiki/Basic_access_authentication

#### Token Authentication

To use token authentication, use the `Authorization` HTTP Header. The key should prefix the `Token`, with whitespace separating the two strings. For example:

```
Authorization: Token <your-token-here>
```

Using curl, this looks like:

```
curl "https://www.courtlistener.com/api/rest/v4/clusters/" \
  --header 'Authorization: Token <your-token-here>'
```

Note that quotes are used to enclose the whitespace in the header.

> [!WARNING]
> **Careful!** A common mistake is to forget the word "Token" in the header.

[Sign in][sign-in] to see your authorization token in this documentation.

[sign-in]: https://www.courtlistener.com/sign-in/

#### Cookie Authentication

To use Cookie Authentication [log into Courtlistener][sign-in] and pass the cookie value using the standard cookie headers.

#### HTTP Basic Authentication

To do HTTP Basic Authentication using curl, you might do something like this:

```
curl --user "harvey:your-password" \
  "https://www.courtlistener.com/api/rest/v4/clusters/"
```

You can also do it in your browser with a url like:

```
https://harvey:your-password@www.courtlistener.com/api/rest/v4/clusters/
```

But if you're using your browser, [you might as well just log in][sign-in].


### Serialization Formats

Requests may be serialized as HTML, JSON, or XML. JSON is the default if no format is specified. The format you wish to receive is requested via the HTTP `Accept` header.

The following media types and parameters can be used:

- **HTML**: The media type for HTML is `text/html`.
- **JSON**: The media type for JSON is `application/json`. Providing the `indent` media type parameter allows clients to set the indenting for the response, for example: `Accept: application/json; indent=2`.
- **XML**: The media type for XML is `application/xml`.

By default, browsers send an `Accept` header similar to:

```
text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
```

This states that `text/html` is the preferred serialization format. The API respects that, returning HTML when requested by a browser and returning JSON when no `Accept` header is provided, because JSON is the default.

If you wish to set the `Accept` header using a tool like cURL, you can do so using the `--header` flag:

```
curl --header "Accept: application/xml" \
  "https://www.courtlistener.com/api/rest/v4/clusters/"
```

All data is serialized using the utf-8 charset.


### Parsing Uploaded Content

If you are a user that has write access to these APIs (most users do not), you will need to use the `Content-Type` HTTP header to explicitly set the format of the content you are uploading. The header can be set to any of the values that are available for serialization or to `application/x-www-form-urlencoded` or `multipart/form-data`, if you are sending form data.


### Filtering

With the exception of the search API, these APIs can be filtered using a technique similar to [Django's field lookups][django-field-lookups].

To see how an endpoint can be filtered, do an `OPTIONS` request on the API and inspect the `filters` key in the response.

In the `filters` key, you'll find a dictionary listing the fields that can be used for filtering along with their types, lookup fields, and any values (aka choices) that can be used for specific lookups.

For example, this uses `jq` to look at the filters on the docket API:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/" | jq '.filters'
```

That returns something like:

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
...
```

This means that you can filter dockets using the ID field, and that you can do exact, greater than or equal, greater than, less than or equal, less than, or range filtering.

You can use these filters with a double underscore. For example, this gets IDs greater than 500 and less than 1,000:

```
curl \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/?id__gt=500&id__lt=1000" | jq '.count'
499
```

It also allows ranges (inclusive):

```
curl \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/?id__range=500,1000" | jq '.count'
501
```

Filters can be combined using multiple `GET` parameters.

There are a few special types of filters. The first are `Related Filters`, which allow you to join filters across APIs. For example, when you are using the docket API, you'll see that it has a filter for the court API:

```json
"court": {
    "type": "RelatedFilter",
    "lookup_types": "See available filters for 'Courts'"
}
```

This means that you can use any of the court filters on the docket API. If you do an `OPTIONS` request on the court API, you'll see its filters:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/courts/" | jq '.filters'
```

Again, one of the filters is the ID field, but it only allows exact values on this API:

```json
"id": {
    "type": "CharFilter",
    "lookup_types": [
        "exact"
    ]
}
```

Putting this together, here's how you look up dockets for a particular court:

```
curl \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/dockets/?court=scotus&id__range=500,1000" | jq '.count'
36
```

This opens up many possibilities. For example, another filter on the `Court` endpoint is for `jurisdictions`. To use it, you would use a GET parameter like `court__jurisdictions=FD`. In this case, the double underscore allows you to join the filter from the other court API to the docket API.

If you want to join a filter, you could do something like `court__full_name__startswith=district`. That would return dockets in courts where the court's name starts with "district".

`RelatedFilters` can span many objects. For example, if you want to get all the Supreme Court `Opinion` objects, you will need to do that with a query such as:

```
curl "https://www.courtlistener.com/api/rest/v4/opinions/?cluster__docket__court=scotus"
```

This uses the `Opinion` API to get `Opinions` that are part of `Opinion Clusters` that are on `Dockets` in the `Court` with the ID of `scotus`. To understand this data model better, see the [case law API documentation][case-law-api].

To use date filters, supply dates in [ISO-8601 format][iso-8601].

A final trick that can be used with the filters is the exclusion parameter. Any filter can be converted into an exclusion filter by prepending it with an exclamation mark. For example, this returns `Dockets` from non-Federal Appellate jurisdictions:

```
curl "https://www.courtlistener.com/api/rest/v4/dockets/?court__jurisdiction!=F"
```

You can see more examples of filters in [our automated tests][api-tests].

[django-field-lookups]: https://docs.djangoproject.com/en/dev/ref/models/querysets/#field-lookups
[iso-8601]: https://en.wikipedia.org/wiki/ISO_8601
[api-tests]: https://github.com/freelawproject/courtlistener/blob/main/cl/api/tests.py



### Ordering

With the exception of the search API, you can see which fields can be used for ordering, by looking at the `ordering` key in an `OPTIONS` request. For example, the `Position` endpoint contains this:

```json
"ordering": [
    "id",
    "date_created",
    "date_modified",
    "date_nominated",
    "date_elected",
    "date_recess_appointment",
    "date_referred_to_judicial_committee",
    "date_judicial_committee_action",
    "date_hearing",
    "date_confirmation",
    "date_start",
    "date_retirement",
    "date_termination"
]
```

Thus, you can order using any of these fields in conjunction with the `order_by` parameter.

Descending order can be done using a minus sign. Multiple fields can be requested using a comma-separated list. This, for example, returns judicial `Positions` ordered by the most recently modified, then by the most recently elected:

```
curl "https://www.courtlistener.com/api/rest/v4/positions/?order_by=-date_modified,-date_elected"
```

Ordering by fields with duplicate values is non-deterministic. If you wish to order by such a field, you should provide a second field as a tie-breaker to consistently order results. For example, ordering by `date_filed` will not return consistent ordering for items that have the same date, but this can be fixed by ordering by `date_filed,id`. In that case, if two items have the same `date_filed` value, the tie will be broken by the `id` field.

### Counting

To retrieve the total number of items matching your query without fetching all the data, you can use the `count=on` parameter. This is useful for verifying filters and understanding the scope of your query results without incurring the overhead of retrieving full datasets.

```
curl "https://www.courtlistener.com/api/rest/v4/opinions/?cited_opinion=32239&count=on"

{"count": 3302}
```

When `count=on` is specified:

- The API returns only the `count` key with the total number of matching items.
- Pagination parameters like `cursor` are ignored.
- The response does not include any result data, which can improve performance for large datasets.

In standard paginated responses, a `count` key is included with the URL to obtain the total count for your query:

```
curl "https://www.courtlistener.com/api/rest/v4/opinions/?cited_opinion=32239"

{
  "count": "https://www.courtlistener.com/api/rest/v4/opinions/?cited_opinion=32239&count=on",
  "next": "https://www.courtlistener.com/api/rest/v4/opinions/?cited_opinion=32239&cursor=2",
  "previous": null,
  "results": [
    // paginated results
  ]
}
```

You can follow this URL to get the total count of items matching your query.

### Field Selection

To save bandwidth, increase serialization performance, and optimize our backend queries, fields can be limited by using the `fields` parameter to select only the fields you want and the `omit` parameter to omit fields you do not. Each parameter accepts a comma-separated list of fields. Double-underscore `__` notation is used to choose or omit nested fields.

This is an important optimization, particularly for resources with large fields.

For example, to only receive the `educations` and `date_modified` fields from the `Judge` endpoint you could do:

```
curl "https://www.courtlistener.com/api/rest/v4/people/?fields=educations,date_modified"
{
  "educations": [
    ...nested values here...
  ],
  "date_modified": "2023-03-31T07:15:28.409594-07:00"
},
...
```

Or, to include only the `date_modified` and `id` fields within each education entry (note the use of the double-underscore):

```
curl "https://www.courtlistener.com/api/rest/v4/people/?fields=educations__date_modified,educations__id"
{
  "educations": [
    {
      "id": 12856,
      "date_modified": "2023-03-31T07:15:28.556222-07:00",
    }
  ]
},
...
```

And to exclude the nested `degree_detail` field within each education entry:

```
curl "https://www.courtlistener.com/api/rest/v4/people/?omit=educations__degree_detail"
{
  "resource_uri": "https://www.courtlistener.com/api/rest/v4/educations/12856/",
  "id": 12856,
  "school": {
    "resource_uri": "https://www.courtlistener.com/api/rest/v4/schools/4240/",
    "id": 4240,
    "is_alias_of": null,
    "date_created": "2010-06-07T17:00:00-07:00",
    "date_modified": "2010-06-07T17:00:00-07:00",
    "name": "University of Maine",
    "ein": 16000769
  },
  "person": "https://www.courtlistener.com/api/rest/v4/people/16214/",
  "date_created": "2023-03-31T07:15:28.556198-07:00",
  "date_modified": "2023-03-31T07:15:28.556222-07:00",
  "degree_level": "jd",
  "degree_year": 1979
}
...
```

We highly recommend using this feature to optimize your requests.

### Pagination

Most APIs can be paginated by using the `page` GET parameter, but that will be limited to 100 pages of results.

As of API v4, deep pagination is generally enabled for requests that are ordered by the `id`, `date_modified`, or `date_created` field. When sorting by these fields, the `next` and `previous` keys of the response are how you must paginate results, and the `page` parameter will not work.

Some API endpoints support slightly different fields for deep pagination:

1. `/api/rest/v4/recap-fetch/` also supports the `date_completed` field.
2. `/api/rest/v4/alerts/` and `/api/rest/v4/docket-alerts/` only support the `date_created` field.

### Rate Limits

Our APIs allow 5,000 queries per hour to authenticated users. Creating more than one account per project, person, or organization is forbidden. If you are in doubt, please contact us before creating multiple accounts.

To debug throttling issues:

1. Try browsing the API while logged into Courtlistener. If this works and your code fails, it usually means that your token authentication is not configured properly, and your code is getting throttled as an anonymous user, not according to your token.
2. Review your recent API usage by looking in your [profile][api-usage], but remember that it will show stats for the browsable API as well.
3. Review the [authentication/throttling tips in our forum][throttling-tips].

If, after checking the above, you need your rate limit increased, [please get in touch][contact] so we can help.

[api-usage]: https://www.courtlistener.com/profile/api/#usage
[throttling-tips]: https://github.com/freelawproject/courtlistener/discussions/1497


### Performance Tips

A few things to consider that may increase your performance:

1. Use [field selection](#field-selection) to limit the serialized payload and defer unused fields, reducing both payload size and database load, especially for large fields.

2. Avoid doing queries like `court__id=xyz` when you can instead do `court=xyz`. Doing queries with the extra `__id` introduces a join that can be expensive.

3. When using the `search` endpoint, smaller result sets are faster. It isn't always possible to tweak your query to return fewer results, but sometimes it is possible to do a more precise query first, thus making a broader query unnecessary. For example, a search for an individual in their expected jurisdiction will be faster than doing it in the entire corpus. This will benefit from profiling in your use case and application.

### Advanced Field Definitions

Placing an HTTP `OPTIONS` request on an API is the best way to learn about its fields, but some fields require further explanation. Click below to learn about these fields.

[Learn About Fields](field-help.md){button}


## APIs

### Case Law APIs

We started collecting case law in 2009 and launched this API in 2013 as the [first][first-api] API for legal decisions.

Use this API to build your own collection of case law, complete complex legal research, and more.

[Learn More](case-law-api.md){button}

[first-api]: https://free.law/2013/11/19/free-law-project-unveils-api-for-american-opinions/

### PACER Data APIs

We have almost half a billion PACER-related objects in the RECAP Archive including dockets, entries, documents, parties, and attorneys. Use these APIs to access and understand this data.

[Learn More](pacer-api.md){button}

### RECAP APIs

Use these APIs to gather data from PACER and to share your PACER data with the public.

[Learn More](recap-api.md){button}

### Pray and Pay API

Request PACER documents that are not yet available in the RECAP Archive. When another user purchases a document you've prayed for, you'll be notified automatically.

Use this API to programmatically create and manage prayer requests.

[Learn More](recap-api.md#pray-and-pay-api){button}

### Search API

CourtListener allows you to search across hundreds of millions of items with advanced fields and operators. Use this API to automate the CourtListener search engine.

[Learn More](search-api.md){button}

### Judge APIs

Use these APIs to query and analyze thousands of federal and state court judges, including their biographical information, political affiliations, education and employment histories, and more.

[Learn More](judge-api.md){button}

### Financial Disclosure APIs

All federal judges and many state judges must file financial disclosure documents to indicate any real or perceived biases they may have.

Use these APIs to work with this information.

[Learn More](financial-disclosure-api.md){button}

### Oral Argument APIs

CourtListener is home to the largest collection of oral argument recordings on the Internet. Use these APIs to gather and analyze our collection.

[Learn More](oral-argument-api.md){button}

### Citation Lookup and Verification API

Use this API to look up citations in CourtListener's database of millions of citations.

This API can look up either an individual citation or can parse and look up every citation in a block of text. This can be useful as a guardrail to help prevent hallucinated citations.

[Learn More](citation-lookup-api.md){button}

### Citation Network APIs

Use these APIs to traverse and analyze our network of citations between legal decisions.

[Learn More](citation-api.md){button}

### Alert APIs

CourtListener is a scalable system for sending alerts by email or [webhook][webhooks-getting-started] based on search queries or for particular cases. Use these APIs to create, modify, list, and delete alerts.

[Learn More](alert-api.md){button}

### Tag APIs

Use these APIs to create, organize, and manage tags on dockets. Tags help you organize and share collections of cases.

[Learn More](tag-api.md){button}

### Visualization APIs

To see and make Supreme Court case visualizations, use these APIs.

[Learn More](visualizations-api.md){button}



## Available Jurisdictions

We currently have **[[ court_count ]]** jurisdictions that can be accessed with our APIs. Details about the jurisdictions that are available, including all abbreviations, can [be found here][jurisdictions].

[jurisdictions]: https://www.courtlistener.com/help/api/jurisdictions/

## Upgrades and Fixes

Like the rest of the CourtListener platform, this API and its documentation are [open source][cl-github]. If it lacks functionality that you desire or if you find this documentation lacking, pull requests providing improvements are encouraged. Just get in touch via our [contact form][contact] to discuss your ideas. Or, if it's something quick, just go ahead and send us a pull request.

Getting this kind support is one of the most rewarding things possible for an organization like ours and is a major goal of [Free Law Project][flp]. Many of the features you use on CourtListener were built this way. We're building something together.

[cl-github]: https://github.com/freelawproject/courtlistener
[flp]: https://free.law

## Maintenance Schedule

There is a weekly maintenance window from 21:00-23:59PT on Thursday nights. If you are scheduling cron jobs or otherwise crawling the API, you may experience downtime during this window.

Additionally, we regularly perform bulk tasks on our servers and maintain [a public calendar][maintenance-calendar] for tracking them. You may encounter larger delays while bulk processing jobs are running.

[maintenance-calendar]: https://www.google.com/calendar/embed?src=michaeljaylissner.com_fvcq09gchprghkghqa69be5hl0@group.calendar.google.com&ctz=America/Los_Angeles


## API Change Log

[View the Change Log](rest-change-log.md){button}

## Copyright

Our data is free of known copyright restrictions.

[![Public Domain Mark][cc-pd-img]][cc-pd]

[cc-pd-img]: https://www.courtlistener.com/static/png/cc-pd.png
[cc-pd]: https://creativecommons.org/publicdomain/mark/1.0/
