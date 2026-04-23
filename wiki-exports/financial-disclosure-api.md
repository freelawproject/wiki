---
title: "Financial Disclosures API"
description: "We collected millions of disclosure records from thousands of federal judges. Use these APIs to query and study this immense dataset."
redirect_from: "/help/api/rest/v4/financial-disclosures/"
wiki_path: "/c/courtlistener/help/api/rest/v4/financial-disclosures/"
---

<p class="lead">Use these APIs to work with financial disclosure records of current and former federal judges.</p>

This data was collected from senate records and information requests we sent to the federal judiciary. You can learn more about which disclosures are included and the limitations of these APIs on [our coverage page for financial disclosures][fd-coverage].

Judicial officers and certain judicial employees in the United States are required to file financial disclosure reports by [Title I of the Ethics in Government Act of 1978][ethics-act]. The Act requires that designated federal officials publicly disclose their personal financial interests to ensure confidence in the integrity of the federal government by demonstrating that they are able to carry out their duties without compromising the public trust.

These APIs were used by the Wall Street Journal in [their 17-part expose][wsj-expose] about the hidden conflicts of federal judges. That led to Congress passing the Courthouse Ethics and Transparency Act to put this information online. It was also used by ProPublica in [their Pulitzer prize winning reporting][propublica-thomas] about failures to disclose gifts and perks.

This data is updated in partnership with organizations using it. Please [get in touch][contact] if you would like to work together to process and ingest the latest disclosure records.

[fd-coverage]: https://www.courtlistener.com/help/coverage/financial-disclosures/
[ethics-act]: https://www.law.cornell.edu/uscode/text/5/13103
[wsj-expose]: https://www.wsj.com/articles/131-federal-judges-broke-the-law-by-hearing-cases-where-they-had-a-financial-interest-11632834421
[propublica-thomas]: https://www.propublica.org/article/clarence-thomas-scotus-undisclosed-luxury-travel-gifts-crow
[contact]: https://www.courtlistener.com/contact/

## Available APIs

The Ethics in Government Act details the types of information required, and prescribes the general format and procedures for the reports themselves.

The APIs described below mirror the Act's language, with APIs corresponding to each required disclosure type.

### Disclosures
`/api/rest/v4/financial-disclosures/`

This API contains information about the main document itself and is the link between the other financial disclosure endpoints and the judges in our system.

### Investments
`/api/rest/v4/investments/`

This API lists the source and type of investment income held by a judge, including dividends, rents, interest, capital gains, or income from qualified or excepted trusts.

### Positions
`/api/rest/v4/disclosure-positions/`

This API lists the positions held as an officer, director, trustee, general partner, proprietor, representative, executor, employee, or consultant of any corporation, company, firm, partnership, trust, or other business enterprise, any nonprofit organization, any labor organization, or any educational or other institution other than the United States.

### Agreements
`/api/rest/v4/agreements/`

This API lists any agreements or arrangements of the filer in existence at any time during the reporting period.

### Non-Investment Income
`/api/rest/v4/non-investment-incomes/`

This API lists the source, type, and the amount or value of earned or other non-investment income aggregating $200 or more from any one source that is received during the reporting period.

### Non-Investment Income (Spouse)
`/api/rest/v4/spouse-incomes/`

This API lists the source and type earned of non-investment income from the spouse of the filer.

### Reimbursements
`/api/rest/v4/reimbursements/`

This API lists the source identity and description (including travel locations, dates, and nature of expenses provided) of any travel-related reimbursements aggregating more than $415 in value that are received by the filer from one source during the reporting period.

### Gifts
`/api/rest/v4/gifts/`

This API lists the source, a brief description, and the value of all gifts aggregating more than $415 in value that are received by the filer during the reporting period from any one source.

### Debts
`/api/rest/v4/debts/`

All liabilities specified by that section that are owed during the period beginning on January 1 of the preceding calendar year and ending fewer than 31 days before the date on which the report is filed.

## Fields

### Understanding the Fields

Like most of our APIs, field definitions can be obtained by sending an HTTP `OPTIONS` request to any of the APIs. For example, this request, piped through [`jq`][jq], shows you the fields of the Gifts API:

```
curl -X OPTIONS "https://www.courtlistener.com/api/rest/v4/gifts/" \
    | jq '.actions.POST'

{
  "resource_uri": {
    "type": "field",
    "required": false,
    "read_only": true,
    "label": "Resource uri"
  },
  "id": {
    "type": "field",
    "required": false,
    "read_only": true,
    "label": "Id"
  },
  "date_created": {
    "type": "datetime",
    "required": false,
    "read_only": true,
    "label": "Date created",
    "help_text": "The moment when the item was created."
  },
  "date_modified": {
    "type": "datetime",
    "required": false,
    "read_only": true,
    "label": "Date modified",
    "help_text": "The last moment when the item was modified. A value in year 1750 indicates the value is unknown"
  },
  "source": {
    "type": "string",
    "required": false,
    "read_only": false,
    "label": "Source",
    "help_text": "Source of the judicial gift. (ex. Alta Ski Area)."
  },
  "description": {
    "type": "string",
    "required": false,
    "read_only": false,
    "label": "Description",
    "help_text": "Description of the gift (ex. Season Pass)."
  },
  "value": {
    "type": "string",
    "required": false,
    "read_only": false,
    "label": "Value",
    "help_text": "Value of the judicial gift, (ex. $1,199.00)"
  },
  "redacted": {
    "type": "boolean",
    "required": false,
    "read_only": false,
    "label": "Redacted",
    "help_text": "Does the gift row contain redaction(s)?"
  },
  "financial_disclosure": {
    "type": "field",
    "required": true,
    "read_only": false,
    "label": "Financial disclosure",
    "help_text": "The financial disclosure associated with this gift."
  }
}
```

Note that each field has the following attributes:

- **`type`**: Indicating the object type for the field.
- **`required`**: Indicating whether the field can have null values. Note that string fields will be blank instead of null.
- **`read_only`**: Indicates whether the field can be updated by users (this does not apply to read-only APIs like the financial disclosure APIs).
- **`label`**: This is a human-readable form for the field's name.
- **`help_text`**: This explains the meaning of the field.

[jq]: https://github.com/jqlang/jq

### Redactions

For security reasons, filers can redact information on their disclosure forms. When a line in a disclosure contains a redaction, we will attempt to set the `redacted` field on that row to `True`. This is your hint that you may want to investigate that row more carefully.

This field can be used as a filter. For example, here are all the investments with redacted information:

```
curl "https://www.courtlistener.com/api/rest/v4/investments/?redacted=True" \
  --header 'Authorization: Token <your-token-here>'
{
  "next": "https://www.courtlistener.com/api/rest/v4/investments/?page=2&redacted=True&cursor=cD0xMjA5NjAyMg%3D%3D",
  "previous": null,
  "results": [
    {
      "resource_uri": "https://www.courtlistener.com/api/rest/v4/investments/5385644/",
      "id": 5385644,
      "date_created": "2023-04-17T11:03:22.404170-07:00",
      "date_modified": "2023-04-17T11:03:22.404185-07:00",
      "page_number": 4,
      "description": "Common Stock",
      "redacted": true,
      "income_during_reporting_period_code": "G",
      "income_during_reporting_period_type": "Dividend",
      "gross_value_code": "P2",
      "gross_value_method": "T",
      "transaction_during_reporting_period": "",
      "transaction_date_raw": "",
      "transaction_date": null,
      "transaction_value_code": "",
      "transaction_gain_code": "",
      "transaction_partner": "",
      "has_inferred_values": false,
      "financial_disclosure": "https://www.courtlistener.com/api/rest/v4/financial-disclosures/34187/"
    },
    ...
  ]
}
```

### Value Codes

Several APIs, including `Investments`, `Debts`, and `Gifts` use form-based value codes to indicate monetary ranges instead of exact values. For example, the letter "J" indicates a value of $1-15,000.

Place an `OPTIONS` request to these endpoints to learn the values of those fields or look in a PDF filing to see the key.

Regrettably, these fields have not been updated by the judiciary in many years, so the highest value code only goes up to $50,000,000. For some judges, this may not be enough to accurately reflect their wealth.

### Inferred Values

`Investment` objects contain the field `has_inferred_values`. This field indicates that we inferred information about an investment based on the layout of the data in the disclosure form.

For example, an investment could have been bought in Q1, while a dividend was paid out in Q2 before being sold in Q4. Often, after the first entry of the investment, later rows in the table are mostly blank. In this instance, we infer the values.

The table below gives a brief example where we would infer that the blank cell below the cell for `AAPL` also refers to `AAPL`:

| Description | Date | Type |
|---|---|---|
| AAPL | 2020-01-01 | Bought |
| -- | 2020-02-01 | Sold |

In this (slightly contrived) example our database would have two rows in the `Investment` table. The first would be for the purchase of the `AAPL` stock, and the second would be for the sale of it.

## API Examples

You can query for investments by stock name, transaction dates and even gross values. For example, the following query is for financial disclosures with individual investments valued above $50,000,000.00. Note that this uses a value code as explained in the general notes above:

```
curl "https://www.courtlistener.com/api/rest/v4/investments/?gross_value_code=P4&fields=investments" \
  --header 'Authorization: Token <your-token-here>'
```

Additionally, you could pinpoint gifts of individual judges when combining the gift database with our judicial database. The following query returns all reported gifts by the late [Ruth Bader Ginsburg][rbg] (her ID is 1213):

```
curl "https://www.courtlistener.com/api/rest/v4/financial-disclosures/?person=1213&fields=gifts" \
  --header 'Authorization: Token <your-token-here>'
```

In 2024, we presented these APIs at the NICAR conference and created [many more examples][nicar-examples] you can explore.

[rbg]: https://www.courtlistener.com/person/1213/ruth-bader-ginsburg/
[nicar-examples]: https://github.com/freelawproject/talks/tree/main/talks/2024/march/NICAR/cracking_the_courts_panel/examples

### Learn More

The following references may help you learn more about these forms:

1. [The official policies guiding financial disclosures][guide-vol02d]
2. [The reporting instructions given to judges and judicial employees][reporting-instructions]
3. [A GAO report on disclosures][gao-report]
4. [The Ethics in Government Act establishing disclosure rules][ethics-bill]

[guide-vol02d]: https://www.uscourts.gov/sites/default/files/guide-vol02d.pdf
[reporting-instructions]: https://www.uscourts.gov/administration-policies/judiciary-financial-disclosure-reports
[gao-report]: https://www.gao.gov/assets/gao-18-406.pdf
[ethics-bill]: https://www.govtrack.us/congress/bills/95/s555

### Security

Please report any security or privacy concerns to [security@free.law][security-email].

[security-email]: mailto:security@free.law
