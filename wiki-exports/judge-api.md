---
title: "Judge and Justice API"
description: "Use these APIs to query and analyze thousands of federal and state judges, including their biographical information, political affiliations, education and employment histories, judgeships, and more."
redirect_from: "/help/api/rest/v4/judges/"
wiki_path: "/c/courtlistener/help/api/rest/v4/judges/"
---

<p class="lead">Use these APIs to query and analyze thousands of federal and state court judges.</p>

This data set is person-centric. All data links back to a particular person.

To learn more about this data, see [our page about it on Free.law][judges-db].

The available APIs include:

- Judges and Appointers
- Positions Held
- Political Affiliations
- Educational Histories
- ABA Ratings
- Retention Events
- Sources

Other types of data are linked to this API and have their own documentation, including:

- [Financial Disclosures][financial-disclosures]
- [PACER Filings][pacer-api]
- [Case Law][case-law-api]
- [Oral Argument Audio][oral-argument-api]

In life, people can serve various roles in the justice system. Therefore, this is not strictly a database of judges, but rather a database of *people* and the positions they hold.

For example, [William Taft][taft] served as president, where he appointed justices, but he was also a Supreme Court justice himself. Therefore, he has a single "person" record in the API, he has one position record for his role as president, and another position record for his role as a justice.

There are a number of "granularity" fields for dates. These are used to indicate how granular a corresponding date is. For example, if we know the year somebody died but not the month or day, we would put `2010-01-01` as the date of death, and set the date of death granularity field to `%Y`.

This approach means that you can still — mostly — filter and sort by these date fields, but with an awareness that the data may be incomplete.

[judges-db]: https://free.law/datasets#judges-db
[financial-disclosures]: financial-disclosure-api.md
[pacer-api]: pacer-api.md
[case-law-api]: case-law-api.md
[oral-argument-api]: oral-argument-api.md
[taft]: https://www.courtlistener.com/person/26/william-howard-taft/

## The APIs

### People (Judges and Appointers)
`/api/rest/v4/people/`

This API contains the central "person" object. As explained above, people can be judges, appointers, or both.

This object holds the core metadata about the person, including their biographical data, positions held, educational history, ABA ratings, and political affiliations.

A few notes:

- Position objects can be quite large, so they are linked in the person object instead of nested within it.

- If the `is_alias_of` field has a value, that means the record represents a nickname for the person referenced in the alias field. Alias records make it possible to find a judge by name, even if they sometimes go by Bob instead of Robert. In our database, this field is a [self-join][self-join].

  In general, you will only want to work with judges where this field is null, indicating a record that represents a person, not an alias to a person.

- The `race` and `gender` fields are not self-reported and should therefore be considered best guesses. We have done our best to gather these fields from reputable sources, but have also supplied values ourselves when it felt appropriate to do so. Some values may be incorrect.

  To create choices for race, we used the U.S. census and added [MENA (it has since been added to the census)][mena].

- The `has_photo` field indicates whether we have a photo for the judge in [our database of judge portraits][judge-portraits].

- The `ftm_*` fields relate to state court judges, who raise money for elections. Use these fields to link judges to their IDs on [Follow The Money][ftm], where you can gather and analyze the details.

  These fields have not been updated in many years, but we can do so as a service.

[self-join]: https://en.wikipedia.org/wiki/Join_(SQL)#Self-join
[mena]: https://en.wikipedia.org/wiki/Middle_East_and_North_Africa
[judge-portraits]: https://free.law/datasets#judges-portraits
[ftm]: https://www.followthemoney.org/

### Positions
`/api/rest/v4/positions/`

Use this API to learn the positions held by a person, including their time as president, in private practice, as a judge, or in any number of other roles in society or the judiciary.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

To filter to positions for a particular person:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/positions/?person=20"
```

### Political Affiliations
`/api/rest/v4/political-affiliations/`

Use this API to learn the political affiliations of a person. Political affiliations are gathered from a number of sources such as ballots or appointments, and have start and end dates.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

### Educations and Schools
`/api/rest/v4/educations/`

Use this API to learn about the educational history of a person, including which schools they went to, when, and what degrees they received. Each education object can include a school object based on data from the Department of Education.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

To filter for judges educated at a particular school:

```
curl -v \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/people/?educations__school__name__contains=Rochester"
```

### ABA Ratings
`/api/rest/v4/aba-ratings/`

These are the American Bar Association ratings that are given to many judges, particularly those that are nominated to federal positions.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

### Retention Events
`/api/rest/v4/retention-events/`

These are the events that keep a judge in a position, such as a retention vote, or reappointment.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.

### Sources
`/api/rest/v4/sources/`

This API keeps a list of sources that explain how we built this database.

To look up field descriptions or options for filtering, ordering, or rendering, complete an HTTP `OPTIONS` request.
