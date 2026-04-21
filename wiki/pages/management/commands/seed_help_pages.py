"""Management command to seed help pages in a /help directory.

Idempotent — safe to run multiple times. Existing help pages are
updated in place; new ones are created.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from wiki.directories.models import Directory
from wiki.pages.models import Page, PageRevision
from wiki.users.models import SystemConfig

HELP_PAGES = [
    {
        "title": "Getting Started",
        "slug": "getting-started-guide",
        "is_pinned": True,
        "content": """\
## Welcome to FLP Wiki

This wiki is the internal knowledge base for Free Law Project.
Anyone with an @free.law email address can sign in and contribute.
This page covers the basics and links to detailed guides on every
feature.

### Signing in

1. Visit the [Sign In](/u/login/) page
2. Enter your @free.law email address
3. Check your inbox for a magic link (valid for 15 minutes)
4. Click the link to sign in — no password needed

Your account is created automatically the first time you sign in.

### Creating a page

1. Navigate to the directory where you want the page
2. Click **New Page**
3. Give it a title and write your content in Markdown
4. Choose a **location** using the directory picker (you can also
   create new directories inline)
5. Set the visibility and editability
6. Write a brief **change message** describing the change
7. Click **Create Page**

### Editing a page

Click the **Edit** button on any page you have permission to edit.
The editor has **Write** and **Preview** tabs — switch to Preview
to see the rendered page before saving. Your changes are saved as
a new revision, so nothing is ever lost. If you leave the page
with unsaved changes, the browser will warn you before navigating
away. See #revisions-guide for more on revision history, diffing,
and reverting.

If someone else is currently editing the page, you'll see a warning
with their name and when they started. You can choose to **Edit
Anyway** to override their lock.

### Reading a page

Each page shows its content along with metadata at the bottom:
the **creator**, any **editors** and **admins** with access, the
current **watchers** (subscribers), the **view count**, and when
the page was last updated.

Headings in the page generate a **Table of Contents** sidebar
(on wider screens) that highlights the section you're currently
reading. Each heading also has a **¶ anchor link** you can click
to get a direct URL to that section.

Code blocks have a **copy button** in the top corner — click it
to copy the code to your clipboard.

### The Actions menu

The **Actions** dropdown on each page gives you access to:

- **Subscribe / Unsubscribe** — toggle email notifications
- **Permissions** — manage who can view and edit (editors only)
- **Move** — move the page to a different directory
- **Feedback** — see pending comments and proposals (editors only)
- **Propose Change** — suggest edits through the review workflow
- **History** — view all revisions
- **What links here** — see which pages link to this one
- **Copy page markdown** — copy the raw Markdown source
- **Delete** — delete the page (requires delete permission)

### Providing feedback

Want to suggest changes without editing a page directly? Use
**Propose Change** from the Actions menu to submit a comment or
propose content changes. The page owner will be notified and can
review your submission. See #proposals-guide for details.

### Subscribing to changes

Click **Subscribe** on any page to get email notifications when
it's updated. You're automatically subscribed to pages you create
or edit. You can also subscribe to an entire directory to get notifications
for all pages within it and its subdirectories.
See #notifications-guide for more on subscriptions, @mentions, and
email notifications.

### Finding pages

- Use the **search bar** in the header to find pages by title or
  content (see #search-guide for advanced filters)
- Browse directories from the [Home](/c/) page
- Use #page-slug wiki links (see #linking-pages)

### Dark mode

The wiki automatically matches your system's light or dark mode
preference. There's no manual toggle — it follows whatever your
operating system or browser is set to.

### Your profile

Visit [Settings](/u/settings/) to set your **display name**. Your
profile picture comes from Gravatar — see #gravatar-guide to set
one up.

### All help topics

**Writing and formatting**

- #markdown-syntax — Markdown reference, the editor, file uploads,
  table of contents, and code block features
- #linking-pages — Wiki link syntax (`#slug`), autocomplete,
  redirects, and backlinks

**Organizing and finding content**

- #directories-guide — Creating, moving, and sorting directories;
  page pinning; directory history
- #search-guide — Full-text search, advanced filters, sorting
  results, and sidebar facets

**Collaboration**

- #notifications-guide — @mentions, subscriptions, and email
  notifications
- #proposals-guide — Comments, proposals, and the review queue

**Access control**

- #permissions-guide — Visibility, editability, directory gates,
  permission inheritance, and groups

**Administration**

- #admin-guide — System owner, admins, archiving users, managing
  groups, and the activity feed
- #gravatar-guide — Setting up your profile picture

**SEO and discoverability**

- #seo-guide — SEO descriptions, sitemap.xml and llms.txt controls,
  Article JSON-LD, canonical URLs, robots.txt, and raw markdown for LLMs
""",
    },
    {
        "title": "Markdown Syntax",
        "slug": "markdown-syntax",
        "content": """\
## Markdown Syntax Guide

Pages are written in Markdown. Here's a reference for the most
common formatting options.

### Text formatting

| Syntax | Result |
|---|---|
| `**bold**` | **bold** |
| `*italic*` | *italic* |
| `~~strikethrough~~` | ~~strikethrough~~ |
| `` `inline code` `` | `inline code` |

### Headings

```
## Heading 2
### Heading 3
#### Heading 4
```

Headings automatically appear in the **Table of Contents** sidebar
on wider screens. The TOC highlights the section you're currently
reading as you scroll. Each heading also gets a **¶ anchor link**
you can click (or copy) to link directly to that section.

### Links and images

```markdown
[Link text](https://example.com)
![Alt text](/files/123/image.png)
```

To link to another wiki page, use the #slug syntax (see #linking-pages).

### Lists

```markdown
- Item one
- Item two
  - Nested item

1. First
2. Second
3. Third
```

### Task lists

```markdown
- [x] Completed task
- [ ] Pending task
```

### Blockquotes

```markdown
> This is a blockquote.
> It can span multiple lines.
```

### Alerts

Use GitHub-style alerts to highlight important information. Start
a blockquote with `[!TYPE]` where TYPE is one of NOTE, TIP,
IMPORTANT, WARNING, or CAUTION:

```markdown
> [!NOTE]
> Useful background information.
```

Here's what each type looks like:

> [!NOTE]
> Useful background information the reader should be aware of.

> [!TIP]
> Helpful advice for getting the most out of something.

> [!IMPORTANT]
> Key information users need to know to achieve their goal.

> [!WARNING]
> Urgent information that needs immediate attention to avoid problems.

> [!CAUTION]
> Warns about risks or negative outcomes of an action.

### Button links

You can make any link render as a button by adding `{button}`
after it:

```markdown
[Get started](https://example.com){button}
[Learn more](https://example.com){button-outline}
[Delete this](https://example.com){button-danger}
```

Three styles are available:

| Syntax | Style |
|---|---|
| `{button}` | Primary (filled, blue) |
| `{button-outline}` | Outline (bordered) |
| `{button-danger}` | Danger (filled, red) |

Here's what they look like:

[Primary button](https://example.com){button}
[Outline button](https://example.com){button-outline}
[Danger button](https://example.com){button-danger}

### Lead paragraph

You can style the opening paragraph of a page as a **lead** — a
larger, bolder introduction that sets the tone before the body
content begins. Wrap it in a `<p>` tag with the `lead` class as
the very first thing in the page content:

```html
<p class="lead">
This is the opening summary of the page. It appears larger
and bolder than the rest of the content.
</p>
```

The lead styling only applies when it is the first element on the
page. A `<p class="lead">` placed anywhere else will render as a
normal paragraph.

### Code blocks

Use triple backticks with an optional language name for syntax
highlighting. Each code block has a **copy button** in the top
corner — click it to copy the contents to your clipboard.

````markdown
```python
def hello():
    print("Hello, world!")
```
````

### Tables

```markdown
| Column A | Column B |
|----------|----------|
| Cell 1   | Cell 2   |
| Cell 3   | Cell 4   |
```

### Horizontal rules

```markdown
---
```

### Uploading files

You can upload files (images, PDFs, documents, etc.) directly into
the editor. There are three ways to upload:

- **Toolbar button** — Click the upload icon in the editor toolbar
  to open a file picker
- **Paste** — Paste an image from your clipboard directly into the
  editor
- **Drag and drop** — Drag a file from your computer onto the editor

The file is uploaded and the appropriate Markdown syntax is inserted
automatically — `![alt](url)` for images and `[filename](url)` for
other files.

**File size limit**: Images can be up to **20 MB**. Other files
can be up to **1 GB**.

**Blocked file types**: Executable files (`.exe`, `.sh`, `.bat`,
`.js`, `.dll`, and similar) cannot be uploaded for security reasons.

**Privacy**: Image metadata (EXIF data such as GPS coordinates,
camera model, and timestamps) is automatically stripped before
upload so it never reaches the server. Uploaded files are served
through signed URLs. Files attached to a private page are only
accessible to users who have permission to view that page.

**Image optimization**: Uploaded images (JPEG, PNG, WebP) are
automatically optimized in the background to reduce file sizes
without noticeable quality loss. The original file is kept if
optimization would make it larger.

### The editor

The Markdown editor has a toolbar with buttons for common
formatting (bold, italic, headings, lists, quotes, links, images,
tables, and file upload). Below the toolbar are **Write** and
**Preview** tabs — click Preview to see the rendered page without
saving.

A status bar at the bottom of the editor shows the current
**line and word count**.

If you navigate away from the page with unsaved changes, the
browser will warn you before leaving.
""",
    },
    {
        "title": "Linking Pages",
        "slug": "linking-pages",
        "content": """\
## Linking Between Wiki Pages

The wiki supports a special syntax for linking to other pages
using their slug.

### Wiki link syntax

Type `#` followed by a page slug:

```
See #markdown-syntax for formatting help.
```

This renders as a clickable link with the page's title.

### How it works

1. When you save a page, the wiki finds all `#slug` references
2. Known slugs are converted to titled links: `[Markdown Syntax](/c/help/markdown-syntax)`
3. Unknown slugs appear as red links, indicating the page doesn't
   exist yet

### Finding a page's slug

The slug is the URL-friendly version of the title. It appears in
the page's URL. For example:

- **Title**: "Getting Started Guide"
- **Slug**: `getting-started-guide`
- **URL**: `/c/help/getting-started-guide`

### Slug redirects

When a page's title changes, the slug changes too. The old slug
is preserved as a redirect, so existing `#old-slug` links
continue to work.

### Autocomplete

In the editor, typing `#` followed by two or more characters
triggers an autocomplete dropdown. Select a page from the list
to insert the correct slug.

### Backlinks ("What links here")

Every page tracks which other pages link to it. Click
**Actions → What links here** to see all incoming wiki links.
This is useful for understanding how a page fits into the broader
wiki — and the wiki uses this information to prevent you from
deleting a page that other pages link to.

### Tips

- Slugs are always lowercase with hyphens: `my-page-title`
- You can link to pages in any directory — slugs are globally unique
- Red links are a good way to plan pages that don't exist yet
""",
    },
    {
        "title": "Permissions Guide",
        "slug": "permissions-guide",
        "content": """\
## Understanding Permissions

The wiki has a flexible permission system that controls who can
view and edit pages and directories. Permissions can be granted
to individual users or to groups.

### Visibility levels

Both pages **and** directories have a visibility setting:

| Level | Who can view |
|---|---|
| **Public** | Everyone, including anonymous visitors |
| **FLP Staff** | Any signed-in user with an @free.law account |
| **Private** | Only users with explicit permission (or the owner) |

### Permission types

| Type | What it allows |
|---|---|
| **View** | Read the page or directory contents |
| **Edit** | Modify content, metadata, and create child items |
| **Admin** | Full control, including managing permissions and deletion |

### How permissions are checked

1. **System owner** — Has full access to everything
2. **Page/directory owner** — Can always view and edit their own items
3. **Page-level permissions** — Explicit grants on a specific page
   (for users or groups)
4. **Directory-level permissions** — Grants that apply to the
   directory and all pages and subdirectories within it
   (for users or groups)

### How settings inherit

Every page and directory has four settings: **visibility**,
**editability**, **search engine inclusion** (sitemap), and
**AI sharing** (llms.txt). All four work the same way:

- **Inherit** (default) — the setting resolves from the nearest
  ancestor directory that has an explicit value. The edit form
  shows a dropdown with the inherited value and "Provided by"
  the source directory, so you always know where it comes from.
- **Explicit override** — pick any other value from the dropdown
  and it takes effect directly, regardless of what ancestors set.

The root directory always has explicit values since there's
nothing above it to inherit from.

| Setting | Options | What it controls |
|---|---|---|
| **Visibility** | Public, FLP Staff, Private | Who can view |
| **Editability** | Restricted, FLP Staff | Who can edit |
| **Search engines** | Yes, No | Sitemap inclusion |
| **AI sharing** | Yes, On request, No | llms.txt inclusion |

When you change a directory's setting, every page and
subdirectory that inherits from it automatically follows.
Items with explicit overrides are unaffected.

### Directories as gates

Directories act as access gates. A private directory hides its
entire contents — pages, subdirectories, and all — from users who
don't have access. Think of it like a folder on a shared drive:
if you can't open the folder, you can't see what's inside.

Specifically:

- A **private directory** returns a 404 to unauthorized users
  (it doesn't reveal that it exists)
- Private subdirectories are hidden from directory listings
- A **private page** inside a private directory requires access
  to *both* the directory and the page
- A page with an explicit **Public** visibility override is
  always viewable via its direct URL, even inside a private
  directory (though it won't appear in the directory listing
  for users who can't access the directory)

### Directory permission inheritance

Permission grants on a directory cascade down to all pages
within it and to child directories. For example, if a user
(or a group they belong to) has **Edit** permission on the
"Engineering" directory, they can edit any page in that
directory and its subdirectories.

Access to a parent directory also implies access to its child
directories. So if you grant someone View on "Engineering",
they can also see "Engineering / DevOps" (unless that child
directory is private and they have no grant on it specifically).

### Applying permissions recursively

From a directory's **Permissions** page, click **Apply to
children** to set all child items to **Inherit** and copy the
directory's permission grants. You'll see two options:

- **Apply to direct pages only** — sets inheritance and copies
  grants to pages directly in this directory
- **Apply recursively** — does the same for all pages *and*
  subdirectories at every level below

This is additive — existing permission grants on child items
are kept; the directory's grants are added on top. Settings
are reset to Inherit so they follow the directory.

### Groups

Users can be organized into groups. When you grant a permission
to a group, every member of that group gets that access. This is
useful for team-based permissions — instead of granting access to
each person individually, grant it to a group like "Engineering"
and manage membership in one place.

Groups can be managed from the [Groups](/g/) page.

### Managing permissions

Click the **Permissions** link on any page or directory to manage
who has access. From there you can:

- Add user or group permissions with a specific access level
- Remove existing permissions
- See all current user and group grants at a glance

### Wiki-link permission warnings

When you edit a page and it contains #slug links to private
pages, the wiki will show a warning modal before saving. This
is advisory — it lets you know that readers of your page may
not be able to follow those links. You can still save; the
warning is just for awareness.

The same modal also handles @mention permissions: if you
mention a user who can't view the page, you can choose to
grant them View or Edit access right from the modal.

### The system owner and admins

The first user to sign in becomes the **system owner**. The
system owner has unrestricted access to all pages, directories,
and admin features.

Additional users can be promoted to admin from the
[Admin Management](/u/admins/) page (accessible from the
gear icon in the header). Admins have:

- Full access to all wiki content
- Access to the Django admin panel
- The ability to promote or demote other admins

The system owner cannot be demoted.

### Editability

In addition to visibility, pages and directories have an
**editability** setting that controls who can edit:

| Setting | Who can edit |
|---|---|
| **Restricted** | Only users with explicit edit permission (the default) |
| **FLP Staff** | Any signed-in user with an @free.law account |

This is useful for pages that should be broadly collaborative —
for example, team wikis or shared documentation where anyone at
FLP should be able to contribute.

### Best practices

- Use **Public** for documentation that should be widely accessible
- Use **FLP Staff** editability for pages where any FLP team member
  should be able to contribute
- Use **Private directories** with group permissions for team
  spaces (e.g., grant the Engineering group Edit on `/c/engineering/`)
- Use **Apply to children** after setting up directory permissions
  to reset inheritance and propagate grants
- Use page-level permission overrides when only specific pages
  need different settings from their directory
- Prefer group-based permissions over per-user grants — they're
  easier to manage as people join and leave teams
""",
    },
    {
        "title": "Search",
        "slug": "search-guide",
        "content": """\
## Searching the Wiki

The wiki has full-text search built in, powered by PostgreSQL.
You can search for pages by title or content from anywhere in the
wiki.

### How to search

- Use the **search bar** in the top navigation bar
- Or visit the [Search](/search/) page directly
- Type your query and press Enter

### What gets searched

Search looks through both page **titles** and page **content**.
Titles are weighted more heavily, so a page whose title matches
your query will appear above pages that only mention it in the body.

### Search tips

- **Use keywords**: Search works best with specific words.
  For example, "deploy staging" will find pages about deploying to
  staging.
- **Partial words don't match**: Searching for "depl" won't find
  "deploy". Use complete words.
- **Multiple words**: All words in your query are searched together.
  Pages matching more of your terms rank higher.
- **Case doesn't matter**: Searching for "Docker" and "docker"
  gives the same results.

### Advanced filters

You can add structured filters to your search query. Type a
filter followed by a space and it will become a visual chip in
the search bar.

| Filter | Example | Description |
|--------|---------|-------------|
| `"exact phrase"` | `"deploy guide"` | Match an exact phrase |
| `in:path` | `in:engineering` | Filter by directory |
| `title:word` | `title:setup` | Search titles only |
| `content:word` | `content:docker` | Search content only |
| `owner:name` | `owner:alice` | Filter by page owner |
| `is:visibility` | `is:public` | Filter by visibility (`public`, `internal`, `private`) |
| `before:date` | `before:2026-01-01` | Updated before date (UTC) |
| `after:date` | `after:2025-06-01` | Updated after date (UTC) |
| `-word` | `-draft` | Exclude pages containing a term |

Filters can be combined: `in:engineering owner:alice "deploy guide"`

Date filters use **UTC** timestamps. For example, `after:2026-03-01`
matches pages updated on or after March 1, 2026 at midnight UTC.

### Sorting results

By default, results are sorted by **relevance**. You can change
the sort order using the dropdown above the results:

- **Relevance** — Best match first (default)
- **Last edited** (newest or oldest first)
- **Date created** (newest or oldest first)
- **Most viewed** — Highest view count first
- **Title A–Z** — Alphabetical order

### Sidebar facets

The search results page has a sidebar with clickable facets that
let you narrow results without typing filter syntax:

- **Visibility** — Filter by Public, FLP Staff, or Private
  (with counts for each)
- **Last edited** — Quick presets: last 7 days, 30 days,
  3 months, or 1 year
- **Directory** — Filter by directory (with counts)

Click a facet to add it as a filter. Active filters appear as
chips that you can remove individually.

### Permission filtering

Search results respect page permissions. You'll only see pages
you have access to view. Private pages you don't have permission
for won't appear in your results, even if they match your query.
""",
    },
    {
        "title": "Gravatar Guide",
        "slug": "gravatar-guide",
        "content": """\
## Setting Up Your Profile Picture

The wiki uses [Gravatar](https://gravatar.com/) to display profile
pictures. Gravatar is a free service that links an avatar image to
your email address — once set up, your picture appears automatically
on any site that supports Gravatar.

### What is Gravatar?

Gravatar stands for **Globally Recognized Avatar**. It's a service
by Automattic (the company behind WordPress) that lets you associate
a profile picture with your email address. When you interact with a
Gravatar-enabled site, your avatar is looked up by your email.

### How the wiki uses Gravatar

The wiki looks up your Gravatar using your **@free.law email
address** — the same one you use to sign in. If you have a Gravatar
linked to that address, it appears next to your name on pages you've
created, edited, or are subscribed to.

### Setting up your Gravatar

1. Go to [gravatar.com](https://gravatar.com/) and click **Sign Up**
2. Create an account using your **@free.law email address**
3. Upload a photo or image you'd like to use as your avatar
4. Save your profile

That's it! Your avatar will start appearing on the wiki within a few
minutes.

### Your display name

You can set a **display name** from [Settings](/u/settings/). This
name appears next to your Gravatar on pages you've created, edited,
or are subscribed to.

### Tips

- Use the same email address you sign in with (@free.law) — the wiki
  won't find your Gravatar if it's linked to a different address
- Choose a clear photo or image that's recognizable at small sizes
  (avatars are often displayed at 20-40px)
- Gravatar is free and your image is served from their CDN, so it
  loads quickly
- If you don't set up a Gravatar, the wiki will show a default
  placeholder or no image at all
""",
    },
    {
        "title": "Directories Guide",
        "slug": "directories-guide",
        "content": """\
## Working with Directories

Directories organize wiki pages into a tree structure, similar
to folders on a file system. Every page lives inside a directory.

### Browsing directories

The [Home](/c/) page is the root directory. From there you can
navigate into subdirectories. Each directory shows its child
directories and pages, with a breadcrumb trail at the top so you
can always find your way back.

### Creating a directory

1. Navigate to the parent directory
2. Click **New Directory**
3. Enter a title and an optional Markdown description
4. Set the visibility and editability
5. Click **Create Directory**

The description is rendered as Markdown on the directory's landing
page — useful for explaining what the directory is for.

### Editing a directory

Click the **Actions** button on a directory and select **Edit**.
You can change the title, description, visibility, and editability.
Include a change message to explain why you're making the change.

### Moving a directory

Click **Actions → Move** to move a directory to a different
parent. All pages and subdirectories inside it move along with it.

Note: Moving a directory updates the URL paths of everything
inside it, so existing bookmarks will break. Wiki links (#slug)
are not affected since they use slugs, not paths.

### Deleting a directory

Click **Actions → Delete** to delete a directory. A directory can
only be deleted if it is **empty** — it must contain no pages and
no subdirectories. Move or delete the contents first.

### Sorting pages

When viewing a directory, you can sort its pages using the sort
controls above the page list:

- **Title** — Alphabetical order
- **Last edited** — Most recently updated first
- **Created** — Newest first
- **Most viewed** — Highest view count first

### Pinning pages

Editors can **pin** a page to keep it at the top of the directory
listing regardless of the sort order. Hover over a page in the
directory listing and click the **pin icon** to toggle it. Pinned
pages show a filled pin icon and always appear above unpinned
pages.

### Directory history

Directories have full revision history, just like pages. Click
**Actions → History** to see all changes to the directory's
metadata (title, description, visibility, editability).

From the history view you can:

- **Compare revisions** — Select two revisions and click
  **Compare** to see a side-by-side diff of what changed
- **Revert** — Restore the directory's title and description
  from a previous revision (permissions are not changed)

### Subscribing to a directory

Click **Actions → Subscribe** on any directory to get email
notifications whenever any page in that directory or its
subdirectories is updated — including pages created in the future.

You can fine-tune notifications by overriding the subscription at
any level — unsubscribe from a subdirectory or specific page
without losing the broader directory subscription. See
#notifications-guide for full details on how subscription
inheritance works.

### Permissions

Directories have their own visibility and permission settings that
act as access gates for everything inside them. See
#permissions-guide for full details on directory permissions,
inheritance, and recursive application.
""",
    },
    {
        "title": "Revisions & History",
        "slug": "revisions-guide",
        "content": """\
## Revisions & History

Every edit to a page or directory is saved as a new revision. No
content is ever lost — you can always view, compare, or restore
previous versions.

### Change messages

Each time you save an edit, you're asked to write a brief **change
message** explaining what you changed and why. These messages
appear in the revision history and in email notifications to
subscribers, so good change messages help everyone understand the
history of a page.

### Viewing revision history

Click **History** (or **Actions → History** for directories) to
see a chronological list of all revisions. Each entry shows:

- The revision number
- Who made the change
- When it was made
- The change message

### Comparing revisions (diffing)

From the history view, select any two revisions using the radio
buttons and click **Compare**. This shows a side-by-side diff with
word-level highlighting:

- **Red/strikethrough** text was removed
- **Green** text was added
- Unchanged text provides context around the changes

This works for both pages (content diffs) and directories
(description and metadata diffs).

### Reverting to a previous revision

From the history view, click **Revert** next to any revision to
restore the page or directory to that point. Reverting creates a
**new** revision (it doesn't delete the intervening history), so
the full timeline is always preserved.

For pages, reverting restores the title and content. For
directories, it restores the title and description (permissions
are not changed).

### Edit locks

When you start editing a page or directory, the wiki acquires a
30-minute **advisory lock** to prevent conflicts. If another user
tries to edit the same item, they'll see a warning showing:

- Who is currently editing
- When they started

The other user can click **Edit Anyway** to override the lock if
they believe it's stale. The lock is automatically released when
you save your changes.

### View counts

Each page tracks how many times it's been viewed. The view count
is displayed at the bottom of the page and can be used as a sort
option in directory listings (sort by "Most viewed"). View counts
are updated periodically in the background.

### Page deletion safeguards

A page cannot be deleted if other pages link to it via #slug wiki
links. This prevents broken links across the wiki. To delete a
page that has incoming links, first remove or update those links
in the other pages.
""",
    },
    {
        "title": "Mentions & Notifications",
        "slug": "notifications-guide",
        "content": """\
## Mentions & Notifications

The wiki keeps you informed about changes through @mentions,
subscriptions, and email notifications.

### @Mentions

You can mention other users by typing `@` followed by their
username in the page content or the change message field:

```
@johndoe can you review this section?
```

When you mention someone:

- They receive an **email notification** with a snippet of the
  content surrounding the mention
- In the editor, typing `@` followed by two or more characters
  triggers an **autocomplete dropdown** so you can find the right
  username
- The autocomplete works in both the main content editor and the
  change message field

### Permission warnings for @mentions

When you save a page that @mentions a user who **cannot currently
view** the page, the wiki shows a warning modal before saving.
From this modal you can:

- **Grant View access** — Give the mentioned user permission to
  read the page
- **Grant Edit access** — Give them permission to edit as well
- **Save anyway** — Save without granting access (the user will
  still get a notification email but won't be able to view the
  page)

This helps you avoid mentioning someone who can't see what you're
talking about.

### Page subscriptions

Click the **Subscribe** button in the Actions menu on any page to
receive email notifications whenever that page is updated.

- You are **automatically subscribed** to pages you create or edit
- Click **Unsubscribe** to stop receiving notifications
- The list of current watchers is shown on the page detail view

### Directory subscriptions

You can also subscribe to an entire **directory** to get
notifications for every page in that directory and all its
subdirectories — including pages created in the future.

1. Navigate to the directory
2. Click **Actions → Subscribe**

This is useful when you want to stay informed about everything in
a topic area without subscribing to each page individually.

### Subscription inheritance

Subscriptions use the same inheritance model as
#permissions-guide and other directory settings: each level in
the directory tree can **override** the subscription state
inherited from above.

By default, you're **not subscribed** to anything. When you
subscribe to a directory, that subscription is inherited by all
pages and subdirectories inside it. You can then override this
at any level:

- **Subscribe to a directory** → all its pages and
  subdirectories inherit the subscription
- **Unsubscribe from a subdirectory** → that subtree is excluded,
  but everything else under the parent directory remains
  subscribed
- **Re-subscribe further down** → overrides the unsubscribe above
  it, just for that subtree

The **closest explicit setting wins** — the wiki walks up the
directory tree from a page to the root and uses the first
subscription record it finds. A page-level override always takes
priority over directory-level settings.

#### Example

1. You subscribe to **Engineering** → you get notifications for
   all pages in Engineering and its subdirectories
2. You unsubscribe from **Engineering/DevOps** → you stop getting
   notifications for DevOps pages, but still get them for
   everything else in Engineering
3. You subscribe to **Engineering/DevOps/CI** → you get
   notifications for CI pages again, even though DevOps is
   unsubscribed

### Email notifications

When a page you're subscribed to is edited or reverted, you
receive an email containing:

- Who made the change
- The change message they wrote
- A link to view the page
- A link to view the diff between the old and new versions
- An unsubscribe link

If you're receiving the notification because of a **directory
subscription**, the email explains this and includes two
unsubscribe options: one for just that page, and one for the
entire directory.

If you can no longer view the page (e.g., permissions changed),
you won't receive notifications for it — regardless of your
subscription settings.

### Unsubscribing

You can unsubscribe in several ways:

- Click **Unsubscribe** in the Actions menu on a page or
  directory
- Click the **unsubscribe link** in any notification email — this
  takes you to a confirmation page
- Many email clients support **one-click unsubscribe** via the
  List-Unsubscribe header, so you may see an unsubscribe button
  directly in your email app
""",
    },
    {
        "title": "Feedback & Proposals Guide",
        "slug": "proposals-guide",
        "content": """\
## Feedback & Proposals

The wiki has two ways to suggest changes without editing a page
directly: **comments** for quick feedback and **proposals** for
suggesting content changes. Both are accessed from the
**Propose Change** link in the Actions menu on any page.

### Leaving a comment

Comments are a lightweight way to ask a question, flag an issue,
or suggest an improvement without editing the page yourself.

1. Navigate to the page
2. Click **Propose Change** in the Actions menu
3. Write your comment in the **Leave a Comment** tab
4. Optionally provide your email address (if not signed in) so
   the editor can reply to you
5. Click **Submit Comment**

The page owner is notified by email. They can reply to your
comment (you'll get an email notification if you provided one)
and then resolve it when it's been addressed.

### Proposing content changes

Proposals let you suggest specific edits to a page's title and
content. The page owner sees a side-by-side diff of exactly what
you changed.

1. Navigate to the page
2. Click **Propose Change** in the Actions menu
3. Switch to the **Propose Changes** tab
4. Edit the title and content in the Markdown editor
5. Write a change message explaining your proposed changes
6. Click **Submit Proposal**

If you're not signed in, you can optionally provide your email
address so you'll be notified when the proposal is reviewed.

### What happens next

- The page owner receives an **email notification** about the
  new comment or proposal
- A **red badge** appears on the page's Actions menu indicating
  pending feedback
- The item waits in a queue for review

### The review queue

Editors and page owners have a unified **review queue** that
collects all pending comments and proposals across every page
they can edit. When you have pending items to review, a
clipboard icon with a red dot appears in the header navigation.

Click it to see all pending items — comments are shown in blue
and proposals in yellow. Each links to the detail view where
you can take action.

### Reviewing comments (for editors)

From the review queue or the page's **Feedback** link:

1. Click a comment to view it
2. Optionally write a **reply** — the commenter will be notified
   by email
3. Click **Resolve** to dismiss the comment once it's been
   addressed

### Reviewing proposals (for editors)

From the review queue or the page's **Feedback** link:

1. Click a proposal to see a **side-by-side diff** comparing
   the current page content with the proposed changes
2. **Accept** — applies the changes to the page. This creates
   a new revision and notifies all subscribers.
3. **Edit before accepting** — toggle the editor to tweak the
   proposed title or content before applying it. This lets you
   fix minor issues without denying the whole proposal.
4. **Deny** — rejects the proposal. You must include a reason,
   which is sent to the proposer by email.

### Who can leave feedback?

Anyone who can **view** a page can leave comments and propose
changes:

- **Signed-in users** — use **Propose Change** in the Actions menu
- **Anonymous visitors** on public pages — use the **Feedback**
  button

Even editors and owners can propose changes when they want their
edits to go through the review workflow rather than editing
directly.

### Tips

- Use **comments** for quick questions, typo reports, or
  suggestions that don't require a specific edit
- Use **proposals** when you know exactly what the content should
  look like
- Write clear change messages so reviewers understand what you
  changed and why
- Comments and proposals don't expire — they stay pending until
  reviewed
""",
    },
    {
        "title": "Admin Guide",
        "slug": "admin-guide",
        "content": """\
## Admin Guide

This page covers administrative features for the wiki system
owner and admin users.

### The system owner

The first user to sign in to a fresh wiki installation
automatically becomes the **system owner**. The system owner:

- Has unrestricted access to all pages, directories, and features
- Cannot be demoted or archived
- Can promote other users to admin

### Admin users

Admin users have elevated privileges similar to the system owner:

- Full access to all wiki content regardless of permissions
- Access to the admin management pages
- Ability to promote or demote other admins

### Managing admins

Visit the [Admin Management](/u/admins/) page (accessible from the
gear icon in the header navigation). From there you can:

- See a list of all users and their roles
- **Promote** a user to admin by clicking the promote button next
  to their name
- **Demote** an admin back to a regular user

Only the system owner and existing admins can access this page.

### Archiving users

From the admin management page, you can **archive** a user to
deactivate their account. Archiving a user:

- Deactivates their account so they can no longer sign in
- Deletes all their active sessions (logs them out immediately)
- Preserves their content contributions (pages, revisions, etc.)

Archived users can be **unarchived** later to restore their access.
This is preferable to deleting accounts since it preserves the
audit trail of who made what changes.

### Managing groups

Groups let you organize users for team-based permissions.
Visit the [Groups](/g/) page to manage groups.

**Creating a group:**

1. Click **New Group**
2. Enter a group name (e.g., "Engineering", "Legal")
3. Click **Create Group**

**Managing members:**

- From a group's detail page, use the username field to add members
- Click **Remove** next to a member to remove them

**Using groups for permissions:**

Once a group exists, you can grant it permissions on any page or
directory from the item's **Permissions** page. All members of the
group inherit that access. This is much easier to manage than
per-user permissions — when someone joins or leaves a team, just
update the group membership.

**Editing and deleting groups:**

- Click **Edit** to rename a group
- Click **Delete** to remove a group (this removes the group's
  permission grants but does not affect member accounts)

### Recent changes (activity feed)

Admins and staff can view a chronological feed of all recent edits
across the entire wiki at [Recent Changes](/activity/). Each entry
shows the page title, who made the change, when, and the change
message. The feed is paginated (50 per page) and can be filtered
to a specific user by clicking their name.

### Best practices for admins

- **Use groups** for team-based access rather than granting
  permissions to individual users
- **Set up directory permissions** with "Apply to children" to
  establish consistent access across entire sections
- **Archive** rather than ignoring departed users — this keeps the
  wiki secure while preserving history
- **Keep the system owner role** limited to one trusted person —
  it cannot be revoked
- Use the **Restricted** editability default for sensitive content,
  and **FLP Staff** editability for collaborative pages anyone at
  FLP should be able to edit
""",
    },
    {
        "title": "SEO & Discoverability Guide",
        "slug": "seo-guide",
        "content": """\
## How the wiki handles SEO and LLM discoverability

The wiki automatically generates SEO metadata for all public pages.
This guide explains what happens behind the scenes, what you can
control as an editor, and how LLM crawlers discover wiki content.

### SEO description

Each page has an optional **SEO Description** field on the edit form
(between the Content textarea and the Visibility selector). This
short summary (up to 300 characters) is used in:

- The HTML `<meta name="description">` tag
- Open Graph (`og:description`) tags for social sharing
- The [/llms.txt](/llms.txt) index for LLM crawlers
- The Article JSON-LD structured data

If you leave it blank, the wiki auto-generates a description from
the first ~160 characters of your page content (with Markdown
stripped). For most pages this works fine, but a hand-written
summary is better for important public-facing pages.

### Canonical URLs

Every HTML page includes a `<link rel="canonical">` tag pointing to
its own URL. This tells search engines that the page is the
authoritative version of its content.

The raw Markdown endpoint (`.md`) also sends a `Link` HTTP header
pointing back to the HTML page as canonical, plus an
`X-Robots-Tag: noindex` header. This prevents search engines from
indexing the Markdown version as a duplicate while keeping it
accessible to LLM crawlers.

### Structured data (JSON-LD)

Public pages include two types of JSON-LD structured data:

1. **BreadcrumbList** — the directory path leading to the page,
   which can appear as breadcrumb trails in search results
2. **Article** — includes the page title, description, publication
   and modification dates, and Free Law Project as the publisher

Private and internal pages do not include any structured data and
are marked with `noindex` to prevent search engine indexing.

### What is sitemap.xml?

A sitemap is a file that lists all the pages on a website so that
search engines like Google and Bing can find and index them. Without
a sitemap, search engines have to discover pages by following links,
which means some pages might be missed. The wiki automatically
generates a sitemap at [/sitemap.xml](/sitemap.xml).

**How it works:**

- Only pages whose effective visibility is **Public** are included
- Only pages whose effective sitemap setting is **Yes** are included
- By default, pages and directories inherit these settings from
  their parent directory (see #permissions-guide for details on
  how settings inherit)
- A page can override its inherited settings — for example, a page
  can explicitly set itself to Public even if its directory is Private
- The sitemap is automatically marked `noindex` by Django (search
  engines follow its links, not index the XML file itself)

**Controlling sitemap inclusion:**

Both pages and directories have an **Include in search engines?**
dropdown on their edit forms. By default this is set to **Inherit**,
meaning the page follows its parent directory's setting. You can
override it to **Yes** or **No** for any individual item.

### What is llms.txt?

[llms.txt](https://llmstxt.org/) is a standard file (like
robots.txt) that helps AI assistants — such as ChatGPT, Claude, and
other large language models — discover and understand your content.
While a sitemap helps search engines, llms.txt is specifically
designed for AI crawlers. The wiki serves this file at
[/llms.txt](/llms.txt).

The file lists pages grouped by directory, with each entry linking
to the raw Markdown (`.md`) version of the page:

```
# FLP Wiki

> Free Law Project's wiki covering legal technology, open legal
> data, and organizational knowledge.

## Engineering

- [CI Pipeline](https://wiki.free.law/c/engineering/ci-pipeline.md): How our CI works

## Optional

- [Getting Started](https://wiki.free.law/c/help/getting-started-guide.md): Intro guide
```

Each entry uses the page's SEO description if set, or an
auto-extracted summary from the content. The llms.txt file itself
has `X-Robots-Tag: noindex` so search engines don't index it.

**Controlling llms.txt inclusion:**

Both pages and directories have a **Share with AI assistants?**
setting with three options:

- **Yes** — the page appears in the main section of llms.txt
- **On request** — the page appears in the "Optional" section,
  signaling to AI assistants that this content is supplementary
  and should be fetched only when relevant
- **No** — the page does not appear in llms.txt at all

Like all settings, this defaults to **Inherit** — the page follows
its parent directory's setting. You can override it on any
individual page or directory. Change it to "Yes" or "On request"
on content you want AI assistants to find.

### robots.txt

The [/robots.txt](/robots.txt) file tells search engine crawlers
what they can and cannot access:

**Allowed:**

- `/c/` — all wiki content pages and directories
- `/llms.txt` — the LLM content index
- Raw Markdown (`.md`) files — for LLM crawlers

**Blocked:**

- `/admin/`, `/api/`, `/u/`, `/search/`, `/files/`,
  `/unsubscribe/`, `/activity/`
- Page action URLs: edit, move, delete, history, diff, revert,
  permissions, subscribe, pin, backlinks
- Directory action URLs: new, new-dir, edit-dir, move-dir,
  delete-dir, history-dir, etc.
- Comments, proposals, and feedback URLs

The robots.txt also includes a `Sitemap:` directive pointing
crawlers to the sitemap.

### What editors should know

- **Set SEO descriptions** on important public pages — a concise,
  hand-written summary outperforms auto-generated ones
- **Settings inherit by default** — new pages and directories
  inherit visibility, sitemap, and llms.txt settings from their
  parent directory. Override any setting on an individual item
  when needed. See #permissions-guide for the full inheritance model
- **You don't need to do anything** for canonical URLs, JSON-LD,
  or robots.txt — these are all automatic
- **Page titles** are used as the `og:title` and Article headline,
  so write clear, descriptive titles
""",
    },
    {
        "title": "External Data Sources Guide",
        "slug": "data-sources-guide",
        "content": """\
## Pulling live data into pages

Pages can fetch JSON from an external API and display the values
inline using simple placeholders. This is useful for dashboards,
status pages, or any content that references data from another
system.

### Setting up a data source

On the page edit form, the **Data Source** section has two fields:

- **API URL** — the full URL of a JSON endpoint
  (e.g. `https://api.example.com/stats.json`). The wiki makes a
  GET request to this URL and parses the response as JSON.
- **Cache (seconds)** — how long to cache the response before
  fetching again. Defaults to 300 (5 minutes). Set a higher
  value for data that changes infrequently.

Leave the API URL blank if the page doesn't need external data.

### Using placeholders

Once a data source is configured, use `[[ key ]]` placeholders
anywhere in your page content. When the page is viewed, each
placeholder is replaced with the corresponding value from the
JSON response.

**Example:** if the API returns:

```json
{
  "total_cases": 5123,
  "last_updated": "2026-03-15"
}
```

Then this markdown:

```
We have [[ total_cases ]] cases as of [[ last_updated ]].
```

Renders as:

> We have 5123 cases as of 2026-03-15.

### Nested keys

Use dot notation to access nested objects. If the API returns:

```json
{
  "stats": {
    "open": 42,
    "closed": 108
  }
}
```

You can write `[[ stats.open ]]` and `[[ stats.closed ]]`.

### Unresolved placeholders

If a placeholder doesn't match any key in the JSON (or the key's
value is `null`), the placeholder is left as-is in the rendered
page. This makes it easy to spot typos or missing data.

### Code blocks are safe

Placeholders inside fenced code blocks (`` ``` ``) or inline code
(`` ` ``) are **not** replaced. This means you can document the
placeholder syntax itself without it being interpreted:

````
```
Use [[ total_cases ]] to show the count.
```
````

### Caching and stale data

The wiki caches each data source response in memory for the
configured TTL. The cache is **shared across pages** — if
multiple pages use the same URL, only one fetch is made and all
pages serve the same cached result. If the API is slow or
unavailable when the cache expires, the wiki serves **stale
cached data** for up to three times the TTL before giving up.
This means a page with a 5-minute TTL can tolerate up to
15 minutes of API downtime without showing missing data.

If the very first fetch fails (no cached data exists), the
placeholders are left as-is.

### Domain allowlist

For security, the wiki only allows data source URLs from approved
domains. By default, only `www.courtlistener.com` is allowed.

If you enter a URL whose domain is not on the allowlist, the form
will show a validation error. Administrators can update the list
by setting the `DATA_SOURCE_ALLOWED_DOMAINS` environment variable
to a comma-separated list of hostnames:

```
DATA_SOURCE_ALLOWED_DOMAINS=www.courtlistener.com,api.example.com
```

If the variable is set to an empty string, all domains are allowed
(not recommended in production).

### Limits and timeouts

- Responses larger than 100 KB are rejected
- API requests time out after 5 seconds
- Only JSON responses are supported

### Tips

- **Use stable API endpoints** — if the URL changes, update the
  page's data source field
- **Set a reasonable cache TTL** — very short TTLs (under 30
  seconds) mean more requests to the external API on every page
  view
- **Keep payloads small** — only include the data you actually
  need in the API response
- **Test the URL** — open it in a browser first to verify the
  JSON structure, then write your placeholders to match
""",
    },
]


class Command(BaseCommand):
    help = "Create or update help pages in the /help directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recreate",
            action="store_true",
            help="Delete existing help pages and recreate them from scratch.",
        )

    def handle(self, *args, **options):
        owner = self._get_owner()
        if owner is None:
            return
        root = self._ensure_root_directory(owner)
        help_dir = self._ensure_help_directory(owner, root)

        if options["recreate"]:
            help_slugs = [p["slug"] for p in HELP_PAGES]
            deleted, _ = Page.all_objects.filter(slug__in=help_slugs).delete()
            self.stdout.write(f"Deleted {deleted} existing help page(s).")

        created = 0
        updated = 0
        for page_data in HELP_PAGES:
            page, was_created = self._upsert_page(page_data, help_dir, owner)
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(f"Help pages: {created} created, {updated} updated.")

    def _get_owner(self):
        """Return the system owner, or the first superuser, or the
        first user."""
        config = SystemConfig.objects.first()
        if config:
            return config.owner

        user = User.objects.filter(is_superuser=True).first()
        if user:
            return user

        user = User.objects.first()
        if user:
            return user

        self.stdout.write(
            "No users exist yet — skipping help page seeding. "
            "They will be created on the next restart after a user signs in."
        )
        return None

    def _ensure_root_directory(self, owner):
        root, _ = Directory.objects.get_or_create(
            path="",
            defaults={
                "title": "Home",
                "owner": owner,
                "created_by": owner,
            },
        )
        return root

    def _ensure_help_directory(self, owner, root):
        help_dir, created = Directory.objects.get_or_create(
            path="help",
            defaults={
                "title": "Help",
                "description": ("Documentation for using the FLP Wiki."),
                "parent": root,
                "owner": owner,
                "created_by": owner,
            },
        )
        if created:
            self.stdout.write("Created /help directory.")
        return help_dir

    def _upsert_page(self, data, help_dir, owner):
        """Create or update a help page. Returns (page, was_created)."""
        is_pinned = data.get("is_pinned", False)
        page, created = Page.objects.get_or_create(
            slug=data["slug"],
            defaults={
                "title": data["title"],
                "content": data["content"],
                "directory": help_dir,
                "owner": owner,
                "visibility": Page.Visibility.PUBLIC,
                "is_pinned": is_pinned,
                "change_message": "Seeded by seed_help_pages",
                "created_by": owner,
                "updated_by": owner,
            },
        )

        if created:
            PageRevision.objects.create(
                page=page,
                title=page.title,
                content=page.content,
                change_message="Initial creation",
                revision_number=1,
                created_by=owner,
            )
            return page, True

        # Update existing page if title, content, or pin state differs
        needs_update = (
            page.content != data["content"]
            or page.title != data["title"]
            or page.is_pinned != is_pinned
        )
        if needs_update:
            page.content = data["content"]
            page.title = data["title"]
            page.is_pinned = is_pinned
            page.change_message = "Updated by seed_help_pages"
            page.updated_by = owner
            page.save()

            last_rev = page.revisions.order_by("-revision_number").first()
            rev_num = (last_rev.revision_number + 1) if last_rev else 1
            PageRevision.objects.create(
                page=page,
                title=page.title,
                content=page.content,
                change_message="Updated by seed_help_pages",
                revision_number=rev_num,
                created_by=owner,
            )

        return page, False
