---
title: "Legal Alert APIs"
description: "Use these APIs to automatically track search queries and cases. Alerts can be sent to your inbox or server."
redirect_from: "/help/api/rest/v4/alerts/"
wiki_path: "/c/courtlistener/help/api/rest/v4/alerts/"
---

<p class="lead">Use these APIs to create, modify, list, and delete search and docket alerts in our system.</p>

Once configured, alerts can notify you by email or with a [webhook event sent to your server][webhooks].

This page focuses on the alerts API itself. To learn more about alerts generally, read the alert documentation.

[Learn About Alerts](https://www.courtlistener.com/help/alerts/){button}

[webhooks]: webhooks.md

## Search Alerts
`/api/rest/v4/alerts/`

Search Alerts update you when there is new information in our search engine.

This system scales to support thousands or even millions of alerts, allowing organizations to stay updated about numerous topics. This is a powerful system when used with [webhooks][webhooks].

Search alerts have three required fields and one optional field:

- **`name`** — A human-friendly name for the alert.
- **`query`** — Search parameters you get from the front end, as a string.
- **`rate`** — How frequently you want to receive email updates. Webhook events are always sent in real time. This field accepts the following values:
  - `rt` — Real time
  - `dly` — Daily
  - `wly` — Weekly
  - `mly` — Monthly
- **`alert_type`** — This is a required field for RECAP Search Alerts, but it is ignored for other types. When used with RECAP Search alerts, this field specifies whether you want alerts for each new case matching the query or for both new cases and new filings. For notifications on cases only, use the `d` type (short for "dockets"). For notifications on both cases and filings, use the `r` type (meaning all of RECAP).

To learn more about this API, make an HTTP `OPTIONS` request:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/alerts/"
```

### Example Usage

Let's say we want to know about case law involving Apple Inc. On the front end, we search for "Apple Inc" (in quotes) and [get query parameters](/?q=%22Apple%20Inc%22&type=o) like:

```
q=%22Apple%20Inc%22&type=o
```

We can create that as an alert with an HTTP `POST` request:

```
curl -X POST \
  --data 'name=Apple' \
  --data 'query=q=%22Apple%20Inc%22&type=o' \
  --data 'rate=rt' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/alerts/"
```

The response:

```json
{
  "resource_uri": "https://www.courtlistener.com/api/rest/v4/alerts/4839/",
  "id": 4839,
  "date_created": "2024-05-02T15:29:32.048912-07:00",
  "date_modified": "2024-05-02T15:29:32.048929-07:00",
  "date_last_hit": null,
  "name": "Apple",
  "query": "q=\"Apple Inc\"",
  "rate": "rt",
  "alert_type": "o",
  "secret_key": "ybSBXwtDcMKI2SxPZDCEx02DSSUF7EEvx1CjOk4f"
}
```

Search Alerts can be modified with HTTP `PATCH` requests. For example, to change the rate to `dly`:

```
curl -X PATCH \
  --data 'rate=dly' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/alerts/4839/"
```

Search Alerts can be deleted with HTTP `DELETE` requests:

```
curl -X DELETE \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/alerts/4839/"
```

To list your alerts, send an HTTP `GET` request with no filters:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/alerts/"
```

## Docket Alerts
`/api/rest/v4/docket-alerts/`

Docket Alerts keep you updated about cases by sending notifications by email or webhook whenever there is new information in our system. Use this API to create, modify, list, and delete Docket Alerts.

Docket Alerts are always sent as soon as an update is available. See [the help page on Docket Alerts][alerts-help] to learn more about how we get updates.

Docket Alerts have two fields you can set:

- **`docket`** — Required: The docket you want to subscribe to or unsubscribe from.

- **`alert_type`** — Whether to subscribe or unsubscribe from the docket.

  This field is part of [@recap.email][recap-email]'s auto-subscribe feature. If you are not using @recap.email or have auto-subscribe disabled, you can ignore this field.

  If you are using @recap.email and have auto-subscribe enabled [in your profile][recap-email-profile], Docket Alerts will be automatically created for you as CourtListener receives notifications about cases. To permanently unsubscribe from a case for which you are receiving notifications from PACER, create an "Unsubscription" for the case.

To learn more about this API, make an HTTP `OPTIONS` request:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/"
```

[alerts-help]: https://www.courtlistener.com/help/alerts/
[recap-email]: https://www.courtlistener.com/help/recap/email/
[recap-email-profile]: https://www.courtlistener.com/profile/recap-email/

### Example Usage

To create a Docket Alert, send a POST request with the `docket` ID you wish to subscribe to.

This example subscribes to docket number 1:

```
curl -X POST \
  --data 'docket=1' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/"
```

The response:

```json
{
  "id": 133013,
  "date_created": "2024-05-02T16:35:58.562617-07:00",
  "date_modified": "2024-05-02T16:35:58.562629-07:00",
  "date_last_hit": null,
  "secret_key": "Xv6sg4xkarzyWdzABi84AyjzV3CslJs9Ldippq3s",
  "alert_type": 1,
  "docket": 1
}
```

To unsubscribe from a docket, you can either delete the alert with an HTTP `DELETE` request:

```
curl -X DELETE \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/133013/"
```

Or, if you are using @recap.email and have auto-subscribe enabled, you can send an HTTP `PATCH` request to change it from a subscription (`alert_type=1`) to an unsubscription (`alert_type=0`):

```
curl -X PATCH \
  --data 'alert_type=0' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/133013/"
```

To list your Docket Alerts, send an HTTP `GET` request with no filters:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/"
```

### Help with Relative Dates Queries

Use relative dates in your queries to keep your searches and alerts dynamically up to date.

[Learn More](https://www.courtlistener.com/help/relative-dates/){button}
