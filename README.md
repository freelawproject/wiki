# FLP Wiki

Internal wiki for [Free Law Project](https://free.law) organizational
documentation. A Django application that supports hierarchical directories,
Markdown pages with versioning, granular permissions, passwordless email auth,
and public-facing pages.

This project — including its code, tests, and this README — was vibe coded
with Claude Code. It has not had extensive human review. Please read everything
with skepticism!


## Quick Start (Development)

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd wiki

# 2. Copy the dev environment file
cp .env.example .env.dev

# 3. Start everything
docker compose -f docker/wiki/docker-compose.yml up --build

# 4. Seed help pages (optional, run once)
docker compose -f docker/wiki/docker-compose.yml exec wiki-django \
    python manage.py seed_help_pages
```

The wiki is now running at **http://localhost:8001**. Visit `/login/` and enter
any `@free.law` email. In development, the magic link is printed to the Django
console — look for the `token=` URL in the container logs.

The first user to sign in automatically becomes the **system owner** with
unrestricted access to all content.


## Architecture

### Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13, Django 6.0 |
| Database | PostgreSQL 16 |
| CSS | Tailwind 3.x (built via npm) |
| JS | Alpine.js, HTMX, EasyMDE (all vendored, no CDN) |
| Templates | Django templates + django-cotton components |
| Task queue | None — daemon service + management commands |
| File storage | Local filesystem (dev), S3 via django-storages (prod) |
| Email | Console (dev), Amazon SES (prod) |
| Containers | Docker Compose for development |
| ASGI server | Gunicorn + Uvicorn workers (prod) |

### Django Apps

```
wiki/
  pages/          Page CRUD, history, diff, revert, search, file uploads
  directories/    Hierarchical directory tree, breadcrumbs
  users/          Passwordless @free.law auth, user profiles, settings
  proposals/      Change proposals workflow
  subscriptions/  Page change notifications, email unsubscribe
  groups/         Group management
  lib/            Shared utilities: permissions, markdown, storage
```

### Settings Pattern

Settings follow CourtListener's split-file pattern. `wiki/settings/__init__.py`
uses wildcard imports to compose the final config from:

```
settings/
  django.py              Core Django settings
  project/
    email.py, logging.py, security.py, testing.py
  third_party/
    aws.py, sentry.py, waffle.py
```

All settings use `environ.FileAwareEnv()` for environment-variable-based
configuration.


## Production Deployment

### Prerequisites

- Docker (or a Python 3.13 environment with PostgreSQL 16)
- An AWS account with S3 and SES configured
- A domain with DNS and HTTPS configured (via a reverse proxy like Nginx or Caddy)
- Docker Compose (or equivalent) to run the daemon service


### Step 1: Environment Variables

Create a `.env` file (or set environment variables directly). Every setting
below is read via `django-environ`'s `FileAwareEnv`, so you can also use
Docker secrets by pointing to files (e.g., `SECRET_KEY_FILE=/run/secrets/key`).

#### Required variables

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | Django secret key. Generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` | `abc123...` |
| `DEBUG` | Must be `False` in production | `False` |
| `DEVELOPMENT` | Must be `False` in production. Controls S3 storage, SES email, debug toolbar, and more | `False` |
| `ALLOWED_HOSTS` | Comma-separated list of domains | `wiki.free.law` |
| `BASE_URL` | Full base URL for email links | `https://wiki.free.law` |
| `DB_HOST` | PostgreSQL hostname | `db.example.com` |
| `DB_NAME` | PostgreSQL database name | `wiki` |
| `DB_USER` | PostgreSQL user | `wiki_user` |
| `DB_PASSWORD` | PostgreSQL password | `(strong password)` |
| `DB_SSL_MODE` | PostgreSQL SSL mode | `require` |

#### AWS S3 (file storage + static files)

When `DEVELOPMENT=False`, Django uses S3 for both media uploads and static
files. You need **two** S3 buckets:

| Variable | Description | Default |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | IAM credentials for S3 | — |
| `AWS_SECRET_ACCESS_KEY` | IAM credentials for S3 | — |
| `AWS_STORAGE_BUCKET_NAME` | Public bucket for static files | `com-freelawproject-wiki-storage` |
| `AWS_PRIVATE_STORAGE_BUCKET_NAME` | Private bucket for uploaded files | `com-freelawproject-wiki-private-storage` |
| `AWS_S3_CUSTOM_DOMAIN` | Custom domain for static file URLs (optional) | `<bucket>.s3.amazonaws.com` |

**Static files bucket** (`AWS_STORAGE_BUCKET_NAME`): Stores collected static
assets (CSS, JS, images). Files are served from the `static/` prefix within the
bucket.

**Private uploads bucket** (`AWS_PRIVATE_STORAGE_BUCKET_NAME`): Stores
user-uploaded files (page attachments, images). All files are stored with
`private` ACL and served via 5-minute signed URLs — no public access needed.

##### S3 bucket configuration

For the **static files bucket**:
- Enable public access (or serve via CloudFront)
- No special CORS or lifecycle rules needed

For the **private uploads bucket**:
- **Block all public access** — files are served via signed URLs
- Suggested bucket policy: grant the IAM user `s3:GetObject`, `s3:PutObject`,
  `s3:DeleteObject`, and `s3:ListBucket`
- No CORS required unless the wiki is on a different domain than S3

##### IAM policy example

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::com-freelawproject-wiki-storage",
        "arn:aws:s3:::com-freelawproject-wiki-storage/*",
        "arn:aws:s3:::com-freelawproject-wiki-private-storage",
        "arn:aws:s3:::com-freelawproject-wiki-private-storage/*"
      ]
    }
  ]
}
```

#### AWS SES (email)

When `DEVELOPMENT=False`, email is sent via Amazon SES (us-west-2 region).

| Variable | Description |
|---|---|
| `AWS_SES_ACCESS_KEY_ID` | IAM credentials for SES (can differ from S3 credentials) |
| `AWS_SES_SECRET_ACCESS_KEY` | IAM credentials for SES |

SES setup requirements:
1. Verify your sending domain (`free.law`) in the SES console
2. The sender address is `noreply@free.law` (configured in `settings/project/email.py`)
3. If your SES account is in sandbox mode, you must also verify recipient addresses
4. Request production access from AWS to send to unverified addresses
5. The IAM user needs the `ses:SendRawEmail` permission

#### Sentry (error tracking, optional)

| Variable | Description |
|---|---|
| `SENTRY_DSN` | Sentry DSN for error reporting. Leave empty to disable |

#### Other optional variables

| Variable | Description | Default |
|---|---|---|
| `TIMEZONE` | Server timezone | `America/Los_Angeles` |
| `MEDIA_ROOT` | Local media root (only used when `DEVELOPMENT=True`) | `wiki/assets/media/` |
| `STATIC_URL` | Static file URL prefix | `static/` |
| `NUM_WORKERS` | Gunicorn worker count | `4` |
| `MAX_REQUESTS` | Gunicorn max requests before worker restart | `2500` |
| `WAFFLE_FLAG_DEFAULT` | Default for missing feature flags | `False` |
| `WAFFLE_SWITCH_DEFAULT` | Default for missing feature switches | `True` |


### Step 2: Build the Docker Image

```bash
docker build -t wiki-django -f docker/django/Dockerfile .
```

The Dockerfile:
- Installs Python dependencies via `uv`
- Installs Node dependencies and builds Tailwind CSS
- Copies the application code
- Runs as `www-data` user


### Step 3: Set Up the Database

Provision a PostgreSQL 16 instance (RDS, self-hosted, etc.) and create the
database:

```sql
CREATE DATABASE wiki;
CREATE USER wiki_user WITH PASSWORD 'strong-password-here';
GRANT ALL PRIVILEGES ON DATABASE wiki TO wiki_user;
```

Run migrations:

```bash
docker run --env-file .env wiki-django migrate
```

The entrypoint's fallthrough case passes arguments to `manage.py`, so
`docker run wiki-django migrate` is equivalent to `python manage.py migrate`.

Create the cache table (used for Django's database-backed cache):

```bash
docker run --env-file .env wiki-django createcachetable
```


### Step 4: Collect Static Files

When `DEVELOPMENT=False`, static files are stored in S3. Run `collectstatic`
to upload them:

```bash
docker run --env-file .env wiki-django collectstatic --noinput
```

This uploads all static files to the `static/` prefix of your
`AWS_STORAGE_BUCKET_NAME` bucket.


### Step 5: Start the Application

```bash
docker run -d \
    --name wiki-django \
    --env-file .env \
    -p 8000:8000 \
    wiki-django web-prod
```

This starts Gunicorn with Uvicorn workers (ASGI). Configuration:
- **Workers**: `NUM_WORKERS` env var (default: 4)
- **Timeout**: 180 seconds
- **Max requests**: `MAX_REQUESTS` env var (default: 2500, with 100 jitter)
- **Bind**: `0.0.0.0:8000`

The first user to log in becomes the system owner.


### Step 6: Reverse Proxy

The application listens on port 8000. Put it behind a reverse proxy (Nginx,
Caddy, etc.) for HTTPS termination.

Key production security settings are enabled automatically when
`DEVELOPMENT=False`:
- `SESSION_COOKIE_SECURE = True`
- `CSRF_COOKIE_SECURE = True`
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
- HSTS: 2 years, with subdomains and preload

Nginx example:

```nginx
server {
    listen 443 ssl;
    server_name wiki.free.law;

    ssl_certificate     /etc/letsencrypt/live/wiki.free.law/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/wiki.free.law/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 16M;
    }
}
```


### Step 7: Daemon Service

The wiki runs periodic tasks via a daemon service (`run_daemon` management
command) that loops and executes tasks on a configurable schedule. Start it
alongside the web server:

```bash
docker run -d \
    --name wiki-daemon \
    --env-file .env \
    wiki-django run_daemon
```

The daemon runs three tasks:

| Task | Default interval | Purpose |
|---|---|---|
| `sync_view_counts` | 5 s | Aggregates `PageViewTally` rows into `Page.view_count` and deletes processed tallies. Avoids write contention on the Page table during reads. |
| `update_search_vectors` | 30 s | Rebuilds PostgreSQL full-text search vectors for all pages, so search results stay current. |
| `cleanup` | 6 hours | Runs miscellaneous cleanup tasks. |

Override intervals with environment variables (values in seconds):

| Variable | Default |
|---|---|
| `DAEMON_SYNC_VIEW_COUNTS_INTERVAL` | `5` |
| `DAEMON_UPDATE_SEARCH_VECTORS_INTERVAL` | `30` |
| `DAEMON_CLEANUP_INTERVAL` | `21600` |


### Step 8: Seed Help Pages (Optional)

Populate the `/help` directory with built-in documentation:

```bash
docker exec wiki-django python manage.py seed_help_pages
```

This is idempotent — safe to run multiple times.


## Complete `.env` Example for Production

```bash
# Django
SECRET_KEY=your-generated-secret-key-here
DEBUG=False
DEVELOPMENT=False
ALLOWED_HOSTS=wiki.free.law
BASE_URL=https://wiki.free.law

# Database
DB_HOST=your-postgres-host.example.com
DB_NAME=wiki
DB_USER=wiki_user
DB_PASSWORD=your-strong-password
DB_SSL_MODE=require

# S3 (file storage + static files)
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_STORAGE_BUCKET_NAME=com-freelawproject-wiki-storage
AWS_PRIVATE_STORAGE_BUCKET_NAME=com-freelawproject-wiki-private-storage

# SES (email)
AWS_SES_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SES_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Sentry (optional)
SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0

# Workers
NUM_WORKERS=4
MAX_REQUESTS=2500
```


## Key Design Decisions

### Passwordless Auth (Magic Links)

No passwords. Users enter their `@free.law` email, receive a link with a
time-limited token (15 min), and click to sign in. Tokens are SHA-256 hashed
before storage. Non-`@free.law` emails are rejected at the form level.

### Unified URL Namespace

Pages and directories share one URL space. The catch-all resolver
(`resolve_path`) checks in order:

1. Does the path match a **Directory**? Render directory view.
2. Does the last segment match a **Page** slug? Render page view.
3. Does it match a **SlugRedirect**? 302 to the current URL.
4. 404.

Fixed routes (`/login/`, `/search/`, `/api/`, etc.) are registered first so
they take priority.

### Wiki Links (`#slug`)

Pages link to each other using `#page-slug` syntax in Markdown content.
During rendering, the `resolve_wiki_links` preprocessor:

- Resolves known slugs to titled links: `#deploy-guide` becomes
  `[Deploy Guide](/engineering/deploy-guide)`
- Resolves old slugs via the `SlugRedirect` table
- Renders unknown slugs as red links (page doesn't exist yet)

The editor provides autocomplete: typing `#` + two characters triggers an
HTMX-powered dropdown of matching page titles.

### Slug Stability

When a page title changes, the slug updates and a `SlugRedirect` is created
mapping the old slug to the page. This means `#old-slug` wiki links and
bookmarks keep working indefinitely.

### Permission Model

Three visibility levels:

| Level | Who can view |
|---|---|
| **Public** | Anyone, including anonymous visitors |
| **Private** | Page owner + system owner only |
| **Restricted** | Users with an explicit permission grant |

Permission types: **View**, **Edit**, **Owner**.

Permissions can be granted at the page level (`PagePermission`) or directory
level (`DirectoryPermission`). Directory permissions cascade — granting Edit
on `/engineering/` gives Edit access to all pages and subdirectories within it.

The **system owner** (first user to sign in) has unrestricted access to
everything.

### Page Versioning

Every edit creates a full-content `PageRevision` snapshot. Users can:

- View revision history with author and change message
- Compare any two revisions with a color-coded diff
- Revert to any previous revision (creates a new revision, notifies subscribers)

Directories also have versioned history (title and description). Reverting a
directory does **not** change its visibility or editability settings.

### No Task Queue

Background work (syncing page view counts, updating search vectors, cleanup)
runs via a daemon service (`run_daemon` management command) instead of Celery
or django-q2. The daemon runs in its own container and loops on a configurable
schedule. See the [Daemon Service](#step-7-daemon-service) section.

### No External CDNs

Alpine.js, HTMX, and EasyMDE are vendored as static files in
`wiki/assets/static-global/js/`. No external network requests for JS or CSS.

### Dark Mode

Uses `prefers-color-scheme` (Tailwind's `darkMode: 'media'`). No manual
toggle — the wiki follows the user's OS/browser setting.

### Page View Counting

Each page view creates a `PageViewTally` row. The daemon service periodically
sums tallies into `Page.view_count` and deletes the processed rows. This
avoids write contention on the Page table during high-traffic reads.


## Running Tests

Tests run inside the Docker container against a disposable test database:

```bash
# Run the full suite
docker compose -f docker/wiki/docker-compose.yml exec wiki-django \
    python -m pytest wiki/ -v

# Run tests for a single app
docker compose -f docker/wiki/docker-compose.yml exec wiki-django \
    python -m pytest wiki/pages/tests.py -v

# Run a specific test class
docker compose -f docker/wiki/docker-compose.yml exec wiki-django \
    python -m pytest wiki/users/tests.py::TestMagicLinkFlow -v
```

Test files live alongside the code they test (`wiki/pages/tests.py`,
`wiki/users/tests.py`, etc.). Shared fixtures are in `wiki/conftest.py`.

### Test Coverage by App

| App | Tests | Covers |
|---|---|---|
| `pages` | 162 | CRUD, history, diff, revert, slugs, search, uploads, markdown, wiki links, view counts, help page seeding |
| `users` | 43 | Login form, magic link flow, logout, settings, profile model |
| `directories` | 100 | Root view, directory detail, edit, history, diff, revert, model methods, page creation in directories |
| `lib` | 36 | Permission checks (system owner, view, edit, restricted, directory inheritance) |
| `subscriptions` | 16 | Subscribe/unsubscribe toggle, notifications, revert notifications, email content, unsubscribe landing |


## Management Commands

```bash
# Run the daemon (periodic tasks: view counts, search vectors, cleanup)
docker exec wiki-django python manage.py run_daemon

# Seed help pages in /help directory (idempotent)
docker exec wiki-django python manage.py seed_help_pages

# Sync page view tallies into Page.view_count (also run by daemon)
docker exec wiki-django python manage.py sync_view_counts

# Update full-text search vectors for all pages (also run by daemon)
docker exec wiki-django python manage.py update_search_vectors

# Run migrations
docker exec wiki-django python manage.py migrate

# Create the cache table (needed once after initial DB setup)
docker exec wiki-django python manage.py createcachetable

# Collect static files to S3 (production)
docker exec wiki-django python manage.py collectstatic --noinput

# Open a Django shell
docker exec -it wiki-django python manage.py shell
```


## Development

### Services

`docker compose -f docker/wiki/docker-compose.yml up` starts:

| Service | Purpose | Port |
|---|---|---|
| `wiki-django` | Django dev server with auto-reload | `localhost:8001` |
| `wiki-postgres` | PostgreSQL 16 | `localhost:5433` |
| `wiki-tailwind` | Tailwind CSS watcher (rebuilds on file changes) | — |
| `wiki-daemon` | Periodic tasks (view counts, search vectors, cleanup) | — |

### Pre-commit Hooks

```bash
pip install pre-commit
pre-commit install
```

Runs ruff (lint + format) and standard checks (large files, merge conflicts,
trailing whitespace, etc.) on every commit.

### Tailwind CSS

Styles are in `wiki/assets/tailwind/input.css` using Tailwind's `@layer`
directives. The config is at `wiki/assets/tailwind/tailwind.config.js`.
The `wiki-tailwind` container watches for changes and rebuilds automatically.

Custom component classes: `.btn-primary`, `.btn-outline`, `.btn-danger`,
`.btn-ghost`, `.card`, `.input-text`, `.alert-*`, `.wiki-content`.

### Adding a New App

1. Create the app under `wiki/` (e.g., `wiki/newapp/`)
2. Add it to `INSTALLED_APPS` in `wiki/settings/django.py`
3. Create `migrations/__init__.py` in the app directory
4. Add URL patterns to `wiki/urls.py`
5. Generate migrations: `docker exec wiki-django python manage.py makemigrations`


## Deployment Checklist

Quick reference for going to production:

- [ ] `SECRET_KEY` set to a strong random value
- [ ] `DEBUG=False` and `DEVELOPMENT=False`
- [ ] `ALLOWED_HOSTS` set to your domain(s)
- [ ] `BASE_URL` set to your HTTPS URL
- [ ] PostgreSQL configured with `DB_SSL_MODE=require`
- [ ] S3 buckets created (public for static, private for uploads)
- [ ] `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` configured
- [ ] SES domain verified, IAM credentials configured
- [ ] `collectstatic` run to upload static files to S3
- [ ] `migrate` and `createcachetable` run against the production database
- [ ] Reverse proxy configured with HTTPS
- [ ] Daemon service running (`run_daemon` for view counts, search vectors, cleanup)
- [ ] Sentry DSN configured (optional)
- [ ] First user logged in to become system owner


## License

AGPL-3.0-only
