Our goal is to make a wiki-like system for a small non-profit.

# Architecture

 - The system will run in a docker image hosted as a pod in k8s. The k8s manifests and cluster are out of scope, but the docker image should be ready to go.
 - AWS Secrets along with django-environ will be used to inject environment variables and other secrets into the pod.
 - S3 for storage via django-storages
 - RDS for DB
 - AWS SES for email
 - Elasticache for redis, if needed, but if all we need is a cache, use django-s3-express-cache so there's no need for redis
 - For front end use tailwind via django-tailwind, django-cotton to build components, and use alpine and HTMX for interactivity. To set up tailwind, copy the approach used in CourtListener.

# Libraries

This is a django project. Use the freelawproject/courtlistener repo for best practices.

Some basics we'll want to use are:
 - Django with uvicorn[standard] and daphne
 - django-environ
 - celery
 - redis (for caching and celery)
 - postgres (for DB)
 - django-pghistory could be useful for tracking old versions of pages, but probably it's better to use bespoke DB tables for this.
 - django-storages for S3 storage of files
 - django-waffle to turn features on and off
 - factory-boy and time-machine for tests. Do not use django fixtures.
 - sentry-sdk for error tracking
 - django-ses for email

For code quality, use pre-commit and ruff as configured in the same way as CourtListener.

For dependencies, use uv, as in CourtListener.

For docker image, copy the approach (as much as reasonable) in CourtListener.

# Functionality

 - Users can create pages
 - Pages contain:
   - A date when they're created or updated
   - A title
   - Content (as markdown)
   - Links to other pages and the links continue working if the pages are renamed
   - A note to explain the reason for each change to the page (like a git commit, sort of)
 - A table of contents should be generated for the page and displayed on the right side of the page. It should maintain the user's location as they scroll by highlighting in some way, and should be clickable to go to HTML anchors of each heading.
 - When pages are changed, old versions are preserved in the database
 - Users can compare the different versions of a page. If they do so, they see a colorful diff of the changes, much like you see in Github when comparing code diffs.
 - When a user creates a page, they become the page's owner, and they are automatically subscribed to the page.
 - If you are subscribed to a page, you get email updates when it changes. The emails contain the message explaining the change and a link to a nicely displayed diff of the page so you can easily see what changed.
 - Users can subscribe or unsubscribe to page updates. If a user does not have permission to view a page, they must never get subscription updates for that page, until their access is restored.
 - Every page can be categorized hierarchically as if in directories
   - Every directory has a landing page showing the subdirectories below it, and the titles of the pages within that directory.
   - Every directory can have a markdown description that is shown on the landing page above the subdirectories for that directory.
 - It should have dark and light themes borrowing from the design of free.law is encouraged. The purple there is nice.
 - Pages can be searched by keyword (no external tools should be used for this, but making search work well is important)

 - Users do not have many settings, but:
   - They can set a profile picture via Gravitar (it's grabbed automatically if already set up)
   - They can set their name
   -

 - Emails allow one-click unsubscription. When the unsubscribe link from the email is clicked, the page the user lands on requires a POST to confirm the unsubscription.

## Page and directory privacy and access

 - There are two important objects: Pages and Directories
 - Pages:
   - Can be public, private, or something in between.
   - If a page is public, everybody on the internet can view it.
   - If a page is private, only the owner can view and edit it, unless additional permissions are granted.
   - Additional people or groups can be given edit, view, or ownership rights to a page.
 - Directory permissions:
   - are used to set the default permission of sub-pages.
   - are used to determine who can view the directory description and contents.
 - A feature allows you to apply the permissions of a directory to all of the pages directly below it or to all the pages and directories below it, recursively. Therefore, directory ownership and permissions are very powerful.  
 - If a page is linked to from a page that has looser access permissions, the user is encouraged to update the target page to have those looser permissions.
 - When browsing directories, users should not see the titles of pages they do not have access to.

## The editor

The editor:
 - uses markdown and has a preview tab to view the rendered markdown before saving it.
 - allows file uploads of any kind. Pictures are shown inline. Other types of files are links that go to S3, like in Github.
 - allows you to link to other pages by doing a hash sign and then typing the other page's title.
 - does smart things like auto-indentation when you press enter, and extra bullets and numbers when you're making those kinds of lists
 - should allow you to paste files in your clipboard or upload them via an interface affordance

## Help pages

The system should use itself to document its functionality. Important pages are:
 - Markdown syntax
 - Instructions for linking across pages
 - How the permission model works

## Authorization

 - Django permissions system
 - Use django auth groups to provide access to pages
 - Administrators can create and modify groups and can adjust the rights of other users
 - Administrators can create other administrators

## Authentication

 - Because this is a tool that will be used by free.law project employees, create accounts automatically when somebody provides a @free.law email address. NEVER allow other email addresses to log into the system.
 - There are no passwords. Login is via secure email links.
 - The first user to log into the system is forever the Owner of the system. This means they have full access to everything.

# Security

 - Use signed S3 URLs or a similar approach to make sure that objects hosted in S3 are not available to unauthenticated users.


