---
title: "Tag APIs"
description: "Use these APIs to create, organize, and manage tags on dockets."
redirect_from: "/help/api/rest/v4/tags/"
wiki_path: "/c/courtlistener/help/api/rest/v4/tags/"
---

<p class="lead">Use these APIs to create, organize, and manage tags on dockets in our system.</p>

Tags help you organize and share collections of cases. You can create public tags that others can view or keep them private for your own use. Tags can be described using markdown to create sharable collections.

This page focuses on the tags API itself. To learn more about tags generally and how to use them in the web interface, read the tags documentation.

[Learn About Tags](https://www.courtlistener.com/help/tags-notes/){button}

## User Tags
`/api/rest/v4/tags/`

User Tags are collections you create to organize dockets. Each tag has a name, optional description, and can be made public or kept private.

### Fields

- **`name`** (required) — A unique slug for your tag (lowercase, no spaces)
- **`title`** (optional) — A human-friendly title for display
- **`description`** (optional) — Markdown description of the tag
- **`published`** (optional) — Boolean, whether the tag is public (default: false)
- **`view_count`** (read-only) — Number of times the tag page has been viewed

To learn more about this API, make an HTTP `OPTIONS` request:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/tags/"
```

### Example Usage

#### Creating a Tag

Create a new tag with a POST request:

```
curl -X POST \
  --data 'name=my-important-cases' \
  --data 'title=My Important Cases' \
  --data 'description=Cases I am tracking for work' \
  --data 'published=false' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/tags/"
```

The response:

```json
{
  "id": 123,
  "date_created": "2024-12-08T10:30:00.000000-08:00",
  "date_modified": "2024-12-08T10:30:00.000000-08:00",
  "user": 456,
  "name": "my-important-cases",
  "title": "My Important Cases",
  "description": "Cases I am tracking for work",
  "published": false,
  "view_count": 0,
  "dockets": []
}
```

#### Updating a Tag

Update a tag with a PATCH request:

```
curl -X PATCH \
  --data 'published=true' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/tags/123/"
```

#### Listing Your Tags

List all your tags with a GET request:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/tags/"
```

#### Deleting a Tag

Delete a tag with a DELETE request:

```
curl -X DELETE \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/tags/123/"
```

## Docket Tags
`/api/rest/v4/docket-tags/`

Docket Tags connect your User Tags to specific dockets. This is a many-to-many relationship managed through this API.

### Fields

- **`tag`** (required) — The ID of the User Tag
- **`docket`** (required) — The ID of the docket to tag

To learn more about this API, make an HTTP `OPTIONS` request:

```
curl -X OPTIONS \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-tags/"
```

### Example Usage

#### Tagging a Docket

Add a docket to a tag with a POST request:

```
curl -X POST \
  --data 'tag=123' \
  --data 'docket=456789' \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-tags/"
```

The response:

```json
{
  "id": 789,
  "tag": 123,
  "docket": 456789
}
```

#### Listing Tagged Dockets

To see all dockets tagged with a specific tag, filter by tag ID:

```
curl -X GET \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-tags/?tag=123"
```

#### Untagging a Docket

To untag a docket, delete the Docket Tag object:

```
curl -X DELETE \
  --header 'Authorization: Token <your-token-here>' \
  "https://www.courtlistener.com/api/rest/v4/docket-tags/789/"
```

## Related APIs

Tags are related to the Pray and Pay program, which allows you to request PACER documents for cases you're tracking. When using Pray and Pay, you can organize the cases you're monitoring using tags, making it easy to manage large collections of cases.

[Learn About Pray and Pay](https://www.courtlistener.com/help/pray-and-pay/){button}
