---
title: "Webhook API"
description: "CourtListener's webhook system allows us to push information to you, enabling bi-directional APIs without polling."
redirect_from: "/help/api/webhooks/"
wiki_path: "/c/courtlistener/help/api/webhooks/about/"
---

<p class="lead">CourtListener's webhook system allows us to push information to you, enabling bi-directional APIs without polling.</p>

To set this up, you create a URL on your server where CourtListener can send data. Then, whenever something important happens in CourtListener, we will POST an "event" to that URL as JSON data. When you receive the event, you can process it and perform whatever actions your system needs in response.

Currently, CourtListener can send webhook events whenever dockets are updated, search alerts are triggered, docket alerts expire, RECAP Fetch tasks complete, or when pray-and-pay requests are granted. If you have other events of interest, please get in touch.

## Pricing

CourtListener is hosted by [Free Law Project][free-law], a non-profit that has "Free" in its name, but we do charge reasonable fees to organizations using advanced features like Webhooks and APIs. We use these fees to maintain our paid and free services.

When we see an organization starting a new project using Webhooks, we will get in touch to discuss the project and set up an agreement that works for everybody.

Questions? Get in touch to start the conversation.

[Contact Us](https://www.courtlistener.com/contact/){button}

## Getting Started With Webhooks

Creating your first webhook working can be complicated. To get an overview of the process, please read our documentation on getting started.

[Get Started](webhooks-getting-started.md){button}

## Overview of Events

### Standard Headers

Each webhook event contains two HTTP headers with additional context for the event:

- **Content-Type**: Indicates the content type of the payload request. For now, our events only support `"application/json"`.

- **Idempotency-Key**: This is a unique 128 bit UUID that corresponds to each event. This value should be used by your application to ensure that you do not process events more than once.

  If you do not take advantage of this feature, we may resend an event that appeared to fail, and you may receive and process it multiple times. More details about this are available in [the section on retries below](#retries).

### Standard Fields

Each webhook event is a JSON hash with two keys, `payload` and `webhook`. The `payload` key contains the specific data for the event that occurred. Its values are described in the [event-specific descriptions below](#event-types).

The `webhook` key helps with maintenance and compatibility. It contains information about the webhook itself. This key should be monitored by administrators and used to track the deprecation schedule for the webhook events.

It has the following structure:

**webhook** *JSON hash*

Information related to the webhook endpoint to which the event belongs.

- **version** *integer* — The specific version of the webhook event.

- **event_type** *integer* — The webhook event type.
  - DOCKET_ALERT = 1
  - SEARCH_ALERT = 2
  - RECAP_FETCH = 3
  - OLD_DOCKET_ALERTS_REPORT = 4
  - PRAY_AND_PAY = 5

- **date_created** *ISO 8601 string* — The date time the webhook endpoint was created.

- **deprecation_date** *ISO 8601 string or null* — The next deprecation date if scheduled, otherwise null.

---

### Webhook Security

Our webhook events will be sent from one of two IP addresses:

1. `34.210.230.218`
2. `54.189.59.91`

We recommend adding these IP addresses to your network allow list and/or verifying that the webhook events you receive come from these addresses.

We also recommend you protect your webhook endpoints by giving them long, random, secret URLs instead of short predictable ones.

Beyond this, our webhook system does not have an authentication mechanism to verify that a POST to your endpoint came from CourtListener. The [decision not to support an authentication mechanism][auth-decision] was made after analyzing the risk of lacking authentication and after completing a review of the Stripe payments platform (which defaults to not using authentication despite being a high-risk environment).

If the need for webhook authentication is a blocker for your organization, [please let us know][contact] and we can revisit this decision.

### Retries and Automatic Endpoint Disablement

Errors across distributed systems are inevitable. To make our webhook system resilient, we automatically retry events POSTed to your application that do not receive a 2xx status code response within one second.

Events are retried up to seven times after the first failure. The retry logic uses an exponential backoff starting at roughly three minutes with a 3x multiplier. As shown in the table below, this gives you around 54 hours to fix any issues in your system.

The next attempt date and time for a specific event can be found [in your webhook logs][webhook-logs].

As webhooks fail to be delivered, we will send emails to your account to inform you of the issue. Email notifications are sent per webhook endpoint based on the first failing event for that endpoint — Notifications are not sent for every failing event, since that would flood your inbox.

This table explains the retry and notification schedule for failing events (in minutes):

| Retry Count | New Delay | Elapsed | Send Failure Notification Email? |
|:-----------:|:---------:|:-------:|:--------------------------------:|
| Initial Event | N/A | 0:00 | No |
| 1 | 0:03 | 0:03 | Yes |
| 2 | 0:09 | 0:12 | No |
| 3 | 0:27 | 0:39 | No |
| 4 | 1:21 | 2:00 | No |
| 5 | 4:03 | 6:03 | Yes |
| 6 | 12:09 | 18:12 | No |
| 7 | 36:27 | 54:39 | Yes |

After a webhook fails eight times, it is disabled in our system and we immediately stop sending it new or undelivered events.

At that point, you will have received two warning emails about the issue, and a third informing you that the endpoint is disabled. Webhooks can be re-enabled at any time, but will get disabled again if errors continue.

Fixed webhook endpoints can be re-enabled in the webhooks panel.

![screenshot of how to re-enable a webhook endpoint](https://www.courtlistener.com/static/png/re-enable-webhook-v2.png)

Once your webhook endpoint is re-enabled, we will continue attempting to deliver failed webhook events that we stopped retrying when the endpoint was disabled, if those events occurred within the last two days.

## Event Types

### Docket Alert Events

If you wish to receive events when particular dockets are updated in CourtListener, you must first "subscribe" to dockets.

A docket subscription can be created in one of three ways:

1. **For normal users**, the best way is [via the CourtListener website itself][recap-alerts].

2. **For servers**, the best way is to use the [Docket Alert API][docket-alert-api].

   For example, this shell code searches for the [Trump Mar-A-Lago][trump-case] case and then subscribes your account to it:

   ```bash
   curl --silent \
     --url 'https://www.courtlistener.com/api/rest/v4/search/?type=d&docket_number=22-cv-81294&case_name=trump' \
     --header 'Authorization: Token <your-token-here>' | \
   jq '.results[0].docket_id' | \
   xargs -I % curl -X POST \
     --url 'https://www.courtlistener.com/api/rest/v4/docket-alerts/' \
     --header 'Authorization: Token <your-token-here>' \
     --data 'docket=%'
   ```

3. **For users** of [@recap.email][recap-email], the best way to subscribe to a case is to have [auto-subscribe turned on in your settings][recap-email-settings].

   When auto-subscribe is on, you will automatically be subscribed to cases when we receive your PACER notifications for them. For users that wish to subscribe to all the cases for which they get PACER notifications, this is usually the best way to do so.

Once subscribed to a case, we will begin POSTing events to your Docket Alert webhook endpoint whenever that case gets new filings.

The docket alert event is a JSON hash with two keys, `webhook` and `payload`. `payload` has a key for new filings that is called `results`.

The shape of the data is thus:

```json
{
  "payload": {
    "results": [...]
  },
  "webhook": {...}
}
```

The `results` key is based on the [Docket Entry API][docket-entry-api]. It has all the same fields except for the `resource_uri` and `tags` fields, which are omitted, and the `docket` field is an `ID` instead of a URL. If you already have access to that API, you can [see an example object here][docket-entry-example], and do an HTTP OPTIONS request to get a description of the fields:

```bash
curl -X OPTIONS \
  --url 'https://www.courtlistener.com/api/rest/v4/docket-entries/' \
  --header 'Authorization: Token <your-token-here>'
```

If you do not yet have access to the Docket Entry API, please [let us know][contact]. In the meantime, another way to see an example event is via [the webhook testing tool][webhook-testing].

### Search Alert Events

[Search alerts in CourtListener][search-alerts] allow you to subscribe to a particular query so that you are sent a webhook event whenever it has new results. For example, you can use search alerts to get a notification whenever a case is cited or whenever a particular keyword appears in a legal decision.

To get search alert events, begin by subscribing to particular queries in CourtListener. This can be done in one of two ways:

1. **For normal users**, subscribe to a query [via the CourtListener website itself][search-alerts].

2. **For servers**, the best way is to use the [Search Alert API][search-alert-api].

   For example, this shell code creates a Search Alert for new legal decisions mentioning the [Obergefell v. Hodges case][obergefell]:

   ```bash
   curl -X POST \
     --url https://www.courtlistener.com/api/rest/v4/alerts/ \
     --header 'Authorization: Token <your-token-here>' \
     --data 'name=My Obergefell Alert' \
     --data 'query=q=Obergefell+v.+Hodges&type=o&order_by=score+desc&stat_Precedential=on&docket_number=14-556' \
     --data 'rate=wly'
   ```

After you've created a Search Alert, we'll send webhook events to your endpoint each time new results are available for your query.

The Search Alert event is a JSON hash with two keys, `webhook` and `payload`. `payload` has two keys, `results` that contains the search results and `alert` for the Search Alert details.

The shape of the data is thus:

```json
{
   "payload": {
      "results": [...],
      "alert": {...}
   },
   "webhook": {...}
}
```

The `results` key is based on the Search API endpoint and has all the same fields. Review [the Search API documentation][search-api] for details on how it works; it is slightly different than all of our other API endpoints.

The `alert` key is based on the [Search Alert endpoint][search-alert-api] and has all the same fields except for the `resource_uri` field, which is omitted.

To get a description of the Search Alert object, do an HTTP `OPTIONS` request to the API endpoint:

```bash
curl -X OPTIONS \
  --url 'https://www.courtlistener.com/api/rest/v4/alerts/' \
  --header 'Authorization: Token <your-token-here>'
```

### Old Docket Alert Events

If a case stops receiving updates due to being terminated or otherwise dormant, we automatically disable any [docket alerts][recap-alerts] that may be configured for it. This helps ease the load on our servers, and helps users in our free tier identify cases that they may wish to stop following.

To help our users manage this, we send a weekly email telling our users about any docket alerts they have that will soon be automatically disabled. This allows them to take one of three actions on the alert:

1. **Do nothing** — If the user does this, the alert will soon be deleted during the next week's automatic process.

2. **Delete the alert** — The user will immediately stop getting alerts for the case.

3. **Re-up the alert** — This tells us that the user wishes to continue getting alerts for the case and pushes out the automatic disablement by about six months.

By subscribing to this webhook your server will get a notification similar to the weekly email we send to users. At that time, your server can decide whether to continue monitoring stagnant cases (by re-upping them; see below) or let the automatic disablement occur.

As with our other events, this webhook event is a JSON hash with two keys, `webhook` and `payload`. `payload` has two keys:

- `disabled_alerts` (Automatically Disabled Alerts):

  Contains a list of docket alerts that have been automatically disabled by our system on terminated cases that haven't had updates for over 180 days. You can re-enable these alerts if they were disabled by mistake.

- `old_alerts` (Old Terminated Cases):

  Contains a list of docket alerts on terminated cases that were last updated about 180 days ago. These alerts will be disabled during the next week's process if you do not re-up them for another six months.

The shape of the data is thus:

```json
{
   "payload":{
      "old_alerts":[
         {
            "id":1,
            "date_created":"2022-09-23T19:53:36.903277-07:00",
            "date_last_hit":null,
            "secret_key":"ehT7V9rmnBNIOV6rTMmMH0x6EvxeA0nYXfpN3Ks3",
            "alert_type":1,
            "docket":1
         }
      ],
      "disabled_alerts":[...]
   },
   "webhook":{...}
}
```

`old_alerts` and `disabled_alerts` contain a list of docket alert objects based on the [Docket Alerts API][docket-alert-api] and have all the same fields.

#### Re-upping a docket alert

If a case has been dormant for a long time, and you wish to continue monitoring it, you must re-up the alert. To do this, send an HTTP PATCH request to the [Docket Alerts API][docket-alert-api]:

```bash
curl -X PATCH \
  --data 'alert_type=1' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/{id}/"
```

Doing the above will tell our system that the alert was recently modified and thus should not be disabled for another six months.

A similar request can be used to disable any docket alert:

```bash
curl -X PATCH \
  --data 'alert_type=0' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-alerts/{id}/"
```

### RECAP Fetch Events

The [RECAP Fetch API][pacer-fetch] lets you use our servers and infrastructure to purchase items on PACER. Your server simply places a `POST` request to the API. In response, the API provides an ID for your request and your download is enqueued for processing.

By listening to this webhook endpoint, your server can monitor your requests and take action when they are complete. This avoids the need to poll the API to check when your request has completed.

As with our other events, this webhook event is a JSON hash with two keys, `webhook` and `payload`.

The shape of the data is thus:

```json
{
   "payload":{...},
   "webhook":{...}
}
```

The `payload` key is based on the [RECAP Fetch API][pacer-fetch] endpoint and has all the same fields.

To get a description of the `payload` object, do an HTTP `OPTIONS` request to the API endpoint:

```bash
curl -X OPTIONS \
  --url 'https://www.courtlistener.com/api/rest/v4/recap-fetch/' \
  --header 'Authorization: Token <your-token-here>'
```

After you set up this endpoint, you will be notified whenever one of your fetch requests terminates in success or failure.

### Pray And Pay Events

The [Pray and Pay system][pray-and-pay] allows users to request PACER documents that are not yet available in CourtListener's RECAP Archive. When a requested document becomes available, users who requested it are notified via email.

To programmatically create and manage prayers, see the [Pray and Pay API documentation][pray-and-pay-api].

By subscribing to this webhook endpoint, your server can be notified when a Pray and Pay request you made has been granted and the document is now available.

As with our other events, this webhook event is a JSON hash with two keys, `webhook` and `payload`.

The shape of the data is thus:

```json
{
   "payload":{
      "id": 1,
      "date_created": "2025-04-16T21:24:18.879312-07:00",
      "status": 2,
      "recap_document": 436149610
   },
   "webhook":{...}
}
```

The `payload` contains the following fields:

- **id** - The unique identifier for this prayer
- **date_created** - When the prayer was originally created
- **status** - The status of the prayer (1 = Waiting, 2 = Granted)
- **recap_document** - The ID of the RECAP document that was requested

Webhook events are only sent when a prayer's status changes to `GRANTED` (status = 2), indicating the document is now available in the RECAP Archive.

You can retrieve the full document details using the [RECAP Document API][recap-endpoint] with the `recap_document` ID provided in the payload.

## Maintenance Schedule

Major server maintenance is scheduled on Thursday nights from 21:00PT to 23:59PT. If you are scheduling cron jobs or otherwise crawling the API, you may experience downtime during this window.

Bulk processing tasks on our servers can create delays while running. We maintain [a public calendar][public-calendar] for tracking these tasks.

## Change Log

- **v1** First release

- **v2** - This release introduces support for Case Law Search Alerts results with nested documents.

  You can now select the webhook version when configuring an endpoint. For most webhook event types, there are no differences between `v1` and `v2`, as the payload remains unchanged.

  In the Search Alert webhook event type, the Oral Arguments search response remains identical between `v1` and `v2`.

  For Case Law and RECAP `v2` now includes nested results, which are based on the new changes introduced in `v4` of the [Search API.][search-api]

[free-law]: https://free.law
[contact]: https://www.courtlistener.com/contact/
[auth-decision]: https://github.com/freelawproject/courtlistener/issues/1650
[webhook-logs]: https://www.courtlistener.com/profile/webhooks/logs/
[recap-alerts]: https://www.courtlistener.com/help/alerts/#recap-alerts
[docket-alert-api]: alert-api.md#docket-alerts
[trump-case]: https://www.courtlistener.com/docket/64911367/trump-v-united-states/
[recap-email]: https://www.courtlistener.com/help/recap/email/
[recap-email-settings]: https://www.courtlistener.com/profile/recap-email/
[docket-entry-api]: pacer-api.md#docket-entries
[docket-entry-example]: https://www.courtlistener.com/api/rest/v4/docket-entries/20615503/
[webhook-testing]: webhooks-getting-started.md#testing-a-webhook-endpoint
[search-alerts]: https://www.courtlistener.com/help/alerts/#search-alerts
[search-alert-api]: alert-api.md#search-alerts
[obergefell]: https://www.courtlistener.com/opinion/2812209/obergefell-v-hodges/
[search-api]: search-api.md
[pacer-fetch]: recap-api.md#pacer-fetch
[pray-and-pay]: https://www.courtlistener.com/help/pray-and-pay/
[pray-and-pay-api]: recap-api.md#pray-and-pay-api
[recap-endpoint]: pacer-api.md#documents
[public-calendar]: https://www.google.com/calendar/embed?src=michaeljaylissner.com_fvcq09gchprghkghqa69be5hl0@group.calendar.google.com&ctz=America/Los_Angeles
