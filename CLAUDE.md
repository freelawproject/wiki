# Wiki Development Guidelines

These guidelines help AI assistants work effectively on the FLP Wiki. Rules marked as MUST are mandatory for AI agents.

Rules and guidance are written with flexibility for humans, but MUST be strictly followed by AI agents.


## Project Structure

```
wiki/
├── assets/            # Static files, templates, JS
│   ├── templates/     # Django templates (base.html, etc.)
│   ├── static/        # Compiled/collected static files
│   └── static-global/ # Global CSS/JS (markdown-editor, etc.)
├── lib/               # Shared utilities (markdown, permissions, storage)
├── pages/             # Page CRUD, uploads, search, file serving
├── directories/       # Directory tree and permissions
├── users/             # Magic link auth, profiles, admin management
├── comments/          # Page comments/feedback
├── proposals/         # Change proposals workflow
├── subscriptions/     # Page/directory email subscriptions
├── groups/            # Group management
└── settings/          # Django settings (split by concern)
    ├── django.py      # Core Django settings
    ├── project/       # Security, logging
    └── third_party/   # AWS, email, etc.
```


## Coding Rules

1. **Imports**: MUST put imports at the top of the file. NEVER do inline imports. The only
   exception is when a circular dependency makes it impossible — in that case, add a comment
   explaining the cycle (e.g., `# Inline import to avoid circular dependency (A ↔ B)`).
   Known circular pairs that require inline imports:
   - `wiki/pages/models.py` ↔ `wiki/lib/markdown.py` (Page model uses WIKI_LINK_RE)
   - `wiki/lib/path_utils.py` → `wiki/pages/models.py` (path_utils imported by Page model)
   - `wiki/pages/views.py` ↔ `wiki/directories/views.py` (mutual view references)
   - `wiki/settings/project/security.py` (conditional production-only import)

2. **Pre-commit**: MUST run `pre-commit run --all-files` and ensure it passes before committing. The project uses ruff for linting and formatting.

3. **URLs**: MUST use Django's `reverse()` function in backend code. NEVER hardcode URL paths.
   In JavaScript, MUST pass URLs from templates via `<script type="application/json">` config
   blocks using `{% url %}` tags. NEVER hardcode URL paths in `.js` files.
   ```python
   # Good
   from django.urls import reverse
   url = reverse("page_edit", kwargs={"path": page.content_path})

   # Bad
   url = f"/c/{page.slug}/edit/"
   ```
   ```html
   <!-- Good: template passes URL to JS via config block -->
   <script type="application/json" id="editor-config">
   { "urls": { "preview": "{% url 'page_preview' %}" } }
   </script>
   ```
   ```javascript
   // Good: JS reads URL from config
   fetch(config.urls.preview, { ... })

   // Bad: hardcoded path in JS
   fetch('/api/preview/', { ... })
   ```

4. **Early exits**: Prefer early returns to prevent deep nesting.
   ```python
   # Good
   if not some_condition:
       return

   # Bad
   if some_condition:
       do_something()
   ```

5. **Unused code**: MUST delete unused code. Don't leave commented-out code.

6. **No code duplication**: MUST NOT duplicate logic across apps. Extract shared utilities to `wiki/lib/` and import them. If two apps need the same helper, it belongs in `wiki/lib/`.

7. **Type hints**: Encouraged for new code but not yet enforced project-wide.

8. **JavaScript vendoring**: MUST vendor all JS libraries locally in `wiki/assets/static-global/js/`.
   NEVER load JS from CDNs at runtime.

10. **Transactions**: MUST wrap multi-step database writes in `transaction.atomic()` when they
   should succeed or fail together. Keep side-effect-only operations (email sends, notifications)
   outside the transaction block so a notification failure doesn't roll back committed data.
   ```python
   # Good
   with transaction.atomic():
       page.save()
       page.create_revision(user)
   notify_subscribers(page.id, ...)

   # Bad — partial failure leaves page without a revision
   page.save()
   page.create_revision(user)
   ```

11. **Alpine.js (CSP build)**: The project uses `@alpinejs/csp`, which does NOT support inline
   JavaScript expressions in templates. MUST follow these rules:
   - Register all components in `wiki/assets/static-global/js/alpine-components.js` using `Alpine.data()`
   - Use `x-data="componentName"` (not inline objects like `x-data="{ open: false }"`)
   - Use methods for actions: `@click="toggle"` (not `@click="open = !open"`)
   - NEVER pass arguments in event handlers: `@click="doThing"` works, `@click="doThing('arg')"` does NOT.
     If you need to vary behavior, create separate methods (e.g., `setUser` / `setGroup` instead of `setTarget('user')`).
   - Use getters for computed values: `x-text="label"` (not `x-text="open ? 'Yes' : 'No'"`)
   - Simple property access works: `x-show="open"`, `x-if="visible"`
   - Do NOT use `x-model` — use `:checked`/`:value` + `@change`/`@input` instead

12. **Directory permission checks at scale**: `can_view_directory`, `can_view_page`, `can_edit_*`,
   `can_administer_*`, and `resolve_effective_value` (`wiki/lib/permissions.py`,
   `wiki/lib/inheritance.py`) each walk the directory's ancestor chain live
   (`d = d.parent`), costing queries proportional to nesting depth per call. That's fine for a
   single item — depth is capped (`MAX_DIRECTORY_DEPTH` in `wiki/lib/path_utils.py`) precisely to
   bound it — but calling one of these functions inside a loop over a listing multiplies that cost
   by N, and N (page/directory count) is NOT capped. MUST NOT write
   `[d for d in directories if can_view_directory(user, d)]` or equivalent over more than one item;
   use `filter_viewable_directories(user, directories)` for view access or
   `filter_administerable_directories(user, directories)` for owner-level access
   (`wiki/lib/permissions.py`) instead — they bulk-resolve visibility/ownership, ancestry, and
   grants in a fixed number of queries. For pages, prefer `viewable_pages_q(user)` — a Q filter
   usable directly in `.filter()` — over looping `can_view_page`. See
   `wiki/lib/tests.py::TestViewableDirectoryQueryCost` and `TestBulkAdministerDirectoryResolver`
   for the query-count regression guards.

13. **Content moves MUST leave a redirect**: a page's URL is `(directory path, slug)`, and
   `Page.save()` regenerates the slug from the title — so a rename, a move to another directory,
   a title revert, and an accepted proposal all change a page's URL. Any code path that relocates
   a page MUST call `record_page_move(page, old_directory, old_slug)`
   (`wiki/lib/page_utils.py`) with the values snapshotted *before* the save; it no-ops when
   nothing moved, so there's no reason to guard the call. NEVER condition it on the slug alone
   (`if page.slug != old_slug`) — that misses a directory-only move. Relocating a directory MUST
   call `record_directory_move(old_subtree_paths)` with `(pk, path)` snapshotted for the directory
   *and every descendant* before the move, since rewriting a directory's path rewrites the URL of
   every page beneath it. This applies to management commands and `ModelAdmin.save_model` as much
   as to views — the admin exposes `slug`, `directory`, and `path` as plain editable fields. See
   `wiki/pages/tests.py::TestRenameAndMoveCombined` and
   `wiki/directories/tests.py::TestMoveDirectory` for the guards.


## Testing

### Running Tests

All `docker compose` commands must be run from `docker/wiki/`, or use
`-f docker/wiki/docker-compose.yml` from elsewhere.

```bash
# Run all tests
docker compose exec wiki-django python -m pytest --tb=short -q

# Run tests for a specific app
docker compose exec wiki-django python -m pytest wiki/pages/tests.py -v

# Run a specific test class
docker compose exec wiki-django python -m pytest wiki/pages/tests.py::TestClassName -v

# Run a specific test method
docker compose exec wiki-django python -m pytest wiki/pages/tests.py::TestClassName::test_method -v
```

### Parallel Test Runs

To run tests in multiple terminals simultaneously, give each a unique test database name via `TEST_DB_NAME`. Use `$$` (the host shell's PID) to automatically get a unique suffix per terminal:

```bash
docker compose exec -e TEST_DB_NAME=test_wiki_$$ wiki-django python -m pytest wiki/pages/ -v
```

This works because each terminal has a stable, unique shell PID. Without `TEST_DB_NAME`, concurrent runs will collide on the default `test_wiki` database.

### Testing Guidelines

- Use pytest with Django's test client (not unittest-style TestCase)
- Fixtures are defined in `wiki/conftest.py` (shared) and per-app test files
- Use `client.force_login(user)` for authenticated requests
- Use `factory-boy` for complex test data

### Browser Tests (Playwright)

For JS-dependent UI behavior that can't be verified with the Django test client,
use Playwright browser tests in `wiki/tests_browser.py`.

```bash
# Run browser tests
docker compose exec wiki-django python -m pytest wiki/tests_browser.py -v
```

Key patterns:
- Use the `browser_page` fixture (not `page`, which collides with conftest)
- Use `live_server` fixture with `@pytest.mark.django_db(transaction=True)`
- Log in via `_force_login(browser_page, live_server, user)` (sets session cookie)
- Wait for API responses with `browser_page.expect_response("**/api/endpoint/**")`
- Playwright + Chromium are installed only in dev builds (`BUILD_ENV=dev`)


## Docker

### Remote sessions (Claude Code on the web)

`.claude/hooks/session-start.sh` brings the stack up in the background, so it is
usually still building when the session starts. Before running anything that
needs the containers — tests, `manage.py`, `docker compose exec` — check the
one-word status file:

```bash
cat /tmp/wiki-stack-status   # starting | ready | failed
```

- `ready` — the stack is up; carry on.
- `starting` — still building. Wait and re-check rather than starting a second stack.
- `failed` — read `/tmp/wiki-session-start.log` for the reason and tell the user.
  Django, postgres and the test suite are unavailable; lint still works.

The stack needs egress to `production.cloudfront.docker.com`,
`pkg-containers.githubusercontent.com`, `deb.debian.org`, `security.debian.org`
and `cdn.playwright.dev`. If the environment's network policy denies any of
them the images cannot be pulled or built; report the blocked hosts instead of
trying to work around them.

### Starting and Stopping

```bash
# Start all services (from repo root)
cd docker/wiki && docker compose up

# Start in background
cd docker/wiki && docker compose up -d

# Stop services
cd docker/wiki && docker compose down
```

The compose file lives at `docker/wiki/docker-compose.yml`. It uses `WIKI_BASE_DIR` (defaults to `../../`, i.e. the repo root) to mount the project into containers.

### Running Multiple Instances (Worktrees)

Multiple compose stacks can run simultaneously (e.g. for git worktrees) by giving
each a unique project name and unique host ports:

```bash
cd docker/wiki && \
  COMPOSE_PROJECT_NAME=wiki-feature \
  DJANGO_HOST_PORT=8002 \
  POSTGRES_HOST_PORT=5434 \
  docker compose up -d
```

Each stack gets isolated containers, networks, and databases. The service names
(`wiki-django`, `wiki-postgres`, etc.) still work within each stack's network.

**Important:** Worktrees don't include `.env.dev` (it's gitignored). Symlink it
before starting the stack:

```bash
ln -s /home/mlissner/Programming/wiki/.env.dev ../wiki-<worktree-name>/.env.dev
```

### Running Commands

Use `docker compose exec` (not `docker exec`) so that compose finds the correct
container for the current project automatically:

```bash
# Run management commands
docker compose exec wiki-django python manage.py [command]

# Create migrations
docker compose exec wiki-django python manage.py makemigrations [app_name]

# Apply migrations
docker compose exec wiki-django python manage.py migrate

# Django shell
docker compose exec -it wiki-django python manage.py shell
```

If you set `COMPOSE_PROJECT_NAME` when starting the stack, you must also set it
when running exec commands, or run from the same `docker/wiki/` directory.

## Tailwind CSS

Tailwind is rebuilt automatically by the `wiki-tailwind` Docker container (runs `npm run dev` in watch mode). NEVER run `npm run build` or `npm run dev` manually — Docker handles it. The compiled `tailwind_styles.css` is gitignored.


## Static Files

NEVER run `collectstatic` in dev. Django serves files directly from `static-global/` via `STATICFILES_DIRS`.


## Dependencies

- **Python**: managed via `pyproject.toml` with `uv`. MUST use `uv` for package management, not `pip`.
- **JavaScript**: `package.json` with `npm`
- **Pre-commit**: `.pre-commit-config.yaml` (ruff linter + formatter)
