---
title: "Advanced Help for API Fields"
description: "Learn more about specific fields in the CourtListener API."
redirect_from: "/help/api/rest/v4/fields/"
wiki_path: "/c/courtlistener/help/api/rest/v4/field-help/"
---

<p class="lead">Some fields in the API can be complicated. This page goes into greater detail about this topic.</p>

## Fields

### Case Names

Case names are a complicated topic, and there are a few common misconceptions about them:

1. **Case names are not unique.** There's nothing stopping a court from using *Johnson v. State* every time a person named Johnson sues the State. Indeed, this is common.

2. **Case names are not stable.** Many cases begin their lives by suing the governor or the attorney general. But these people change as a result of elections or appointments, and so the names of these cases often change too.

3. **Case names don't always contain v.** Instead, many cases start with *In Re* or other abbreviations.

We've done our best to normalize case names wherever we can, following Blue Book conventions. Some things we regularly do include:

1. We normalize all the different ways people write "United States" (U.S.A., United States of America, U.S., etc.) All of these variations simply become "United States", as the Blue Book requires.

2. We remove some abbreviations, like *Et al*.

3. We replace any instance of vs. with v.

4. We do our best to make the case names Title Case rather than UPPERCASE, as many courts publish them.

The result of all this work is that we have pretty good case names.

In the API, you'll see case names in a variety of places due to the fact that they can change over time. For example, there are `case_name` fields on the `Docket` object and also on the `Opinion Cluster` objects. In almost all instances, these values are the same but some cases have different values for the `Docket` than for an `Opinion Cluster`, so we keep this data in duplicate.

Case names can also vary considerably in length, and we've identified three different types of case names:

1. `case_name`: This is a typical case name that can be used in almost all references. An example might be *Roe v. Wade*.

2. `case_name_short`: This is a shortened one or two word case name that can be used in legal writing after the standard case name has been provided by the author. An example of this might be simply *Roe* used, "As was stated in *Roe*..."

3. `case_name_full`: This is the full list of plaintiffs and defendants in a case, sometimes going on for hundreds of words, and often including titles or other information. For example: *Roe Et Al v. Wade, District Attorney of Dallas County*.

All cases have at least one of these values, many have two values, and some have all three. A `case_name_short` was generated algorithmically for every case possible, but about 40% of cases were too complicated for our program to process and so they were left blank. Editors have ensured that every Supreme Court case from 1945 to 2018 has a `case_name_short` value.

`case_name` is available for the majority of cases, except those that were imported from Resource.org, which only provided `case_name_full` values. When that happened, there was no way for us to condense a `case_name_full`, so until an editor is available to review them, they will lack this value. All cases have either a `case_name` or a `case_name_full` value.

Our advice is to use a `case_name` if it is available and to fall back on the `case_name_full` if it is not. If you are interested in sponsoring trained humans to improve this data, please [get in touch][contact].

### The `absolute_url` Field

The `absolute_url` field shows the URL where a resource can be seen live on the site. It is absolute in the sense that it should never change and will always be backwards compatible if changes are ever needed.

In some cases you might start with a URL from CourtListener, and you might want to look up the item in the API. Generally, CourtListener URLs are designed to contain an ID that can be used in the API to look it up, following a pattern like:

```
/$type/$id/$name-of-the-case/
```

There are three sections:

1. **$type**: This is the type of object that has been returned, for example, "docket" indicates that you have gotten a docket as your result.

2. **$id**: This is a numeric ID for the document. This value increments as we add content to the system. Note that due to deletions and modifications the numeric IDs are not always sequential, but they will never be duplicated within a document type.

3. **$name-of-the-case**: This is the "[slug][slug-wiki]" of the document, and generally mirrors its case name. This value can change if we clean up a case name, but provided it is not omitted completely, this part of the URL can be any value without affecting the page that is loaded.

   Put another way, we load pages based on the `$id` and `$type`, not by the name of the case.

### File Download Fields

API responses will give you the URL path to a resource such as a PDF or MP3, but not the domain. These are often in a field named `local_path` or similar.

To download a resource, create a full URL by concatenating the path from the API response with `https://storage.courtlistener.com/`.

[contact]: https://www.courtlistener.com/contact/
[slug-wiki]: https://en.wikipedia.org/wiki/Slug_%28publishing%29
