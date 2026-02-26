"""Management command to seed help pages in a /help directory.

Idempotent — safe to run multiple times. Existing help pages are
updated in place; new ones are created.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from wiki.directories.models import Directory
from wiki.pages.models import Page, PageRevision

HELP_PAGES = [
    {
        "title": "Getting Started",
        "slug": "getting-started-guide",
        "content": """\
## Welcome to FLP Wiki

This wiki is the internal knowledge base for Free Law Project.
Anyone with an @free.law email address can sign in and contribute.

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
Your changes are saved as a new revision, so nothing is ever lost.
See #revisions-guide for more on revision history, diffing, and
reverting.

If someone else is currently editing the page, you'll see a warning
with their name and when they started. You can choose to **Edit
Anyway** to override their lock.

### Proposing changes

Don't have edit access to a page? You can still contribute by
clicking **Propose Changes** to submit a change proposal. The page
owner will be notified and can review, accept, or deny your
proposal. See #proposals-guide for details.

### Subscribing to changes

Click **Subscribe** on any page to get email notifications when
it's updated. You're automatically subscribed to pages you create.
See #notifications-guide for more on @mentions and email
notifications.

### Finding pages

- Use the **search bar** in the header to find pages by title or
  content
- Browse directories from the [Home](/c/) page
- Use #page-slug wiki links (see #linking-pages)

### Sorting directory listings

When viewing a directory, you can sort pages by **title**, **last
edited**, **created date**, or **most viewed** using the sort
controls above the page list.

### Dark mode

The wiki automatically matches your system's light or dark mode
preference. There's no manual toggle — it follows whatever your
operating system or browser is set to.

### Your profile

Visit [Settings](/u/settings/) to set your **display name**. Your
profile picture comes from Gravatar — see #gravatar-guide to set
one up.

### More help

- #markdown-syntax — How to format your pages
- #linking-pages — How to link between pages
- #directories-guide — Working with directories
- #revisions-guide — Revision history, diffing, and reverting
- #notifications-guide — @mentions, subscriptions, and emails
- #proposals-guide — Proposing changes to pages
- #permissions-guide — Understanding visibility and permissions
- #admin-guide — Admin features and user management
- #search-guide — How search works
- #gravatar-guide — Setting up your profile picture
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

Headings automatically appear in the **Table of Contents** sidebar.

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

### Code blocks

Use triple backticks with an optional language name:

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

**File size limit**: The maximum upload size is **1 GB** per file.

**Privacy**: Uploaded files are served through signed URLs. Files
attached to a private page are only accessible to users who have
permission to view that page.
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
- A **public page** is always viewable, even if its directory
  is private (public means public)

### Pages can't be more open than their directory

A page in a private directory cannot be set to public. This
prevents accidentally exposing content that the directory is
meant to protect. If you try to:

- **Create** a public page in a private directory — you'll get
  an error asking you to keep the page private
- **Edit** a page to public when it's in a private directory —
  same error
- **Move** a public page into a private directory — blocked with
  a message to change the page to private first

To make a page public, first make its directory public (or move
the page to a public directory).

### Default visibility

When you create a new page in a directory, the visibility
defaults to match the directory. A new page in a private
directory will default to private, saving you from having to
change it manually.

### Directory permission inheritance

Permissions on a directory cascade down to all pages within it
and to child directories. For example, if a user (or a group
they belong to) has **Edit** permission on the "Engineering"
directory, they can edit any page in that directory and its
subdirectories.

Access to a parent directory also implies access to its child
directories. So if you grant someone View on "Engineering",
they can also see "Engineering / DevOps" (unless that child
directory is private and they have no grant on it specifically).

### Applying permissions recursively

When you set up permissions on a directory, you can copy those
permissions to all child pages and subdirectories at once.
From the directory's **Permissions** page, click **Apply to
children**. You'll see two options:

- **Apply to direct pages only** — Sets the visibility and
  copies permission grants to pages directly in this directory
- **Apply recursively** — Does the same for all pages *and*
  subdirectories at every level below

This is additive — existing permissions on child items are
kept; the directory's permissions are added on top.

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
**Admin** link in the header). Admins have:

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

**Important constraint**: A page or directory cannot be set to
"FLP Staff" editability if its visibility is "Private". This prevents
granting edit access to users who can't even view the content.

When you apply permissions recursively from a directory, the
editability setting is also propagated to all child pages and
subdirectories.

### Best practices

- Use **Public** for documentation that should be widely accessible
- Use **FLP Staff** editability for pages where any FLP team member
  should be able to contribute
- Use **Private directories** with group permissions for team
  spaces (e.g., grant the Engineering group Edit on `/c/engineering/`)
- Use **Apply to children** after setting up directory permissions
  to propagate them to existing pages
- Use page-level permissions when only specific people need access
  to a particular page
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

### Permission filtering

Search results respect page permissions. You'll only see pages
you have access to view. Private pages you don't have permission
for won't appear in your results, even if they match your query.

### How it works under the hood

For the technically curious: the wiki uses PostgreSQL's built-in
full-text search rather than a separate search engine. Here's how
it works:

1. Each page has a **search vector** — a pre-computed index of all
   the words in its title and content, stored as a PostgreSQL
   `tsvector` column.
2. Title words are given **weight A** (highest priority) and content
   words are given **weight B**, so title matches rank higher.
3. When you search, your query is converted to a `tsquery` and
   matched against these vectors using a **GIN index** for speed.
4. Results are ranked by relevance using PostgreSQL's `ts_rank`
   function.
5. Search vectors are refreshed periodically (every 10 minutes) by
   a background job, so brand-new pages may take a few minutes to
   become searchable.

This approach keeps the architecture simple — no external search
service to manage — while providing fast, ranked full-text search
across all wiki content.
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

### Directory history

Directories have full revision history, just like pages. Click
**Actions → History** to see all changes to the directory's
metadata (title, description, visibility, editability).

From the history view you can:

- **Compare revisions** — Select two revisions and click
  **Compare** to see a side-by-side diff of what changed
- **Revert** — Restore the directory's title and description
  from a previous revision (permissions are not changed)

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

### Subscriptions

Click the **Subscribe** button on any page to receive email
notifications whenever that page is updated.

- You are **automatically subscribed** to pages you create
- Click **Unsubscribe** to stop receiving notifications
- The list of current subscribers is shown on the page detail view

### Email notifications

When a page you're subscribed to is edited or reverted, you
receive an email containing:

- Who made the change
- The change message they wrote
- A link to view the diff between the old and new versions
- An unsubscribe link

If you can no longer view the page (e.g., permissions changed),
you won't receive notifications for it.

### Unsubscribing

You can unsubscribe in two ways:

- Click **Unsubscribe** on the page itself
- Click the **unsubscribe link** in any notification email — this
  takes you to a confirmation page

Many email clients also support **one-click unsubscribe** via the
List-Unsubscribe header, so you may see an unsubscribe button
directly in your email app.
""",
    },
    {
        "title": "Proposals Guide",
        "slug": "proposals-guide",
        "content": """\
## Proposing Changes

The proposals feature lets anyone suggest edits to a page, even
if they don't have edit permission. This is useful for corrections,
additions, or improvements from people outside the page's usual
editors.

### How to propose a change

1. Navigate to the page you want to suggest changes to
2. Click **Propose Changes** (this appears instead of **Edit**
   when you don't have edit access)
3. Edit the content in the Markdown editor
4. Write a change message explaining your proposed changes
5. Click **Submit Proposal**

If you're not signed in, you can optionally provide your email
address so you'll be notified when the proposal is reviewed.

### What happens next

- The page owner receives an **email notification** about the
  new proposal
- A **red badge** appears on the page indicating pending proposals
- The proposal waits in a queue for review

### Reviewing proposals (for editors)

If you have edit permission on a page with pending proposals:

1. Click the **Proposals** link on the page (look for the red
   badge indicating the count of pending proposals)
2. You'll see a list of pending and previously reviewed proposals
3. Click on a proposal to see a **side-by-side diff** comparing
   the current page content with the proposed changes

### Accepting a proposal

When reviewing a proposal, click **Accept** to apply the changes.
You can optionally modify the proposed content before accepting.
Accepting a proposal:

- Updates the page content with the proposed changes
- Creates a new revision in the page's history
- Notifies all subscribers about the change
- Sends an email to the proposer letting them know it was accepted

### Denying a proposal

Click **Deny** to reject a proposal. You can include a reason,
which will be sent to the proposer via email so they understand
why the change wasn't accepted.

### Tips

- Write clear change messages so reviewers understand what you
  changed and why
- If you have a lot of changes to suggest, consider breaking them
  into smaller, focused proposals
- Proposals don't expire — they stay pending until reviewed
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
**Admin** link in the header navigation). From there you can:

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
]


class Command(BaseCommand):
    help = "Create or update help pages in the /help directory."

    def handle(self, *args, **options):
        owner = self._get_owner()
        root = self._ensure_root_directory(owner)
        help_dir = self._ensure_help_directory(owner, root)

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
        from wiki.users.models import SystemConfig

        config = SystemConfig.objects.first()
        if config:
            return config.owner

        user = User.objects.filter(is_superuser=True).first()
        if user:
            return user

        user = User.objects.first()
        if user:
            return user

        self.stderr.write(
            "No users exist. Create a user first (visit /u/login/)."
        )
        raise SystemExit(1)

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
        page, created = Page.objects.get_or_create(
            slug=data["slug"],
            defaults={
                "title": data["title"],
                "content": data["content"],
                "directory": help_dir,
                "owner": owner,
                "visibility": Page.Visibility.PUBLIC,
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

        # Update existing page content
        if page.content != data["content"]:
            page.content = data["content"]
            page.title = data["title"]
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
