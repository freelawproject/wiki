---
title: "Supreme Court Visualization API"
description: "Use these APIs to make and modify Supreme Court Visualizations."
redirect_from: "/help/api/rest/v4/visualizations/"
wiki_path: "/c/courtlistener/help/api/rest/v4/visualizations/"
---

## Overview
`/api/rest/v4/visualizations/`

<p class="lead">Use this API to programmatically create and manage Supreme Court network visualizations in CourtListener.</p>

All visualizations are associated with a user and are private by default. When you GET these endpoints, you will see data for visualizations that have been made public by their owners or that you have created yourself.

To learn more about opinion clusters, see the [case law API documentation][case-law-api]. To learn more about citations between decisions see the [citation API documentation][citation-api].

[case-law-api]: case-law-api.md
[citation-api]: citation-api.md

## Creating Visualizations

To create a new visualization, send an HTTP `POST` with a title, a starting cluster ID, and an ending cluster ID:

```
curl -X POST \
  --data 'cluster_start=/api/rest/v4/clusters/105659/' \
  --data 'cluster_end=/api/rest/v4/clusters/111891/' \
  --data 'title=A map from Trop to Salerno' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/visualizations/"
```

The `cluster_start` and `cluster_end` parameters use URLs instead of IDs.

The above command creates a visualization unless there are no connections between the start and end clusters or the network becomes too large to generate.

Once created, the visualization will have nested JSON data representing the visualization itself, a list of clusters that are in it, and various other metadata.

## Editing and Deleting Visualizations

Changing data for an existing visualization can be done via an HTTP `PATCH` request. For example, to make a visualization publicly accessible:

```
curl -X PATCH \
  --data 'published=True' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/visualizations/1/"
```

Similar commands can be used to update other non-readonly fields.

To soft-delete a visualization, flip the `deleted` field to `True`. To hard-delete, send an HTTP `DELETE` request.

## Deprecation Notice

> [!WARNING]
> Our system for visualizing Supreme Court networks has not gotten much traction among users, and is largely deprecated as of late 2025.

If you are interested in creating, deleting, or updating visualizations, you can still do so through our APIs, but it is no longer possible to display visualizations on CourtListener.com itself. Moving forward, to support existing users, the only way to display visualizations is through their embed links.

To embed a visualization on a website you control, use code like the following on your site:

```html
<iframe height="540" width="560" src="https://www.courtlistener.com/visualizations/scotus-mapper/YOUR_ID_HERE/embed/" frameborder="0" allowfullscreen></iframe>
```

Just replace YOUR_ID_HERE with the ID of your visualization, and it should work on your website.

The following `GET` parameters may be used to adjust the display:

- **`type`** — Use this to set the y-axis. `spread` opens up the visualization with random locations for the nodes so they can all be seen. `geneology` makes many paths lighter to highlight the most direct paths. `spaeth` uses the Supreme Court Database's vote count and decision direction fields.
- **`xaxis`** — The x-axis may be set to either equal spacing (`cat`) or accurate chronological spacing (`time`)
- **`dos`** — Use this to set the Degree of Separation, which represents the maximum number of hops between the first and last nodes.

For example, GET parameters like these will provide a clean, equally spaced chart with up to five nodes of separation: `?type=geneology&xaxis=cat&dos=5`.

We apologize for this deprecation and hope you understand that we cannot always maintain all the features and experiments we undertake.

## Frequently Asked Questions

### Why do the case circles change size?

Circles change size based on the number of citations to it by other cases in the network. The more cases that cite to *Case A*, the larger it will be. The only exception to this rule is the rightmost case on network (with the most recent date). For visual clarity, this anchor case is always represented with a large circle.

### How can I find out what the cases in my network mean?

This tool will not read the cases for you, but it will make your reading more efficient. You can read opinion text directly by clicking on opinions in the visualization. You can see all the Supreme Court Database information for a case. Information will open in a separate window and includes issue area, legal provision involved, and detailed voting information. By using SCDB information and skimming opinion text, you can figure out what is going on in the case fairly quickly. Some networks also have helpful user descriptions.

### Why did my network default to 2-degrees?

We do not generate 3-degree networks when it will contain more than 70 cases. We have found networks larger than 70 are too unwieldy and so default those networks to 2-degrees.

### Why is a case missing from my network?

When the Supreme Court cites to recently decided cases, the citation form is non-standard such as citing to *Slip. Op* or *555 S.Ct ___*. This currently confounds our automatic citation parser. It's a problem we're working on.

### How do I embed a network in my blog?

Use the iframe code shown in the deprecation notice above. Replace YOUR_ID_HERE with the ID of your visualization. You can then put this code in your WordPress blog (or LibGuides site, etc.) just as you would embed a video from YouTube.

### What do you mean by "Degree of Dissent"?

We use *Degree of Dissent* (DoD) in our visualizations of Supreme Court networks to indicate the average level of disagreement in the cases shown. For example, in a network that shows two cases, each with unanimous 9-0 votes, there would be no dissent, and so the score would be 0. By contrast, if a network had only two cases, each with 5-4 decisions, the DoD would be 1.0, indicating a highly dissenting network.

Mathematically, the DoD for a given case is calculated by multiplying the number of dissents by 0.25. This means that a 9-0 case will have the same DoD as a 8-0 case (0.0) and a 6-3 will have the same DoD as 5-3 case.

In some cases you may see that the DoD is not using all of the cases in a network, stating something like: "Degree of Dissent: 0.73 for 16 cases of 17." This occurs because some cases do not have vote information in the Supreme Court Database (Spaeth).
