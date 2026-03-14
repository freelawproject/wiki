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
   ```python
   # Good
   from django.urls import reverse
   url = reverse("page_edit", kwargs={"path": page.content_path})

   # Bad
   url = f"/c/{page.slug}/edit/"
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

9. **Alpine.js (CSP build)**: The project uses `@alpinejs/csp`, which does NOT support inline
   JavaScript expressions in templates. MUST follow these rules:
   - Register all components in `wiki/assets/static-global/js/alpine-components.js` using `Alpine.data()`
   - Use `x-data="componentName"` (not inline objects like `x-data="{ open: false }"`)
   - Use methods for actions: `@click="toggle"` (not `@click="open = !open"`)
   - Use getters for computed values: `x-text="label"` (not `x-text="open ? 'Yes' : 'No'"`)
   - Simple property access works: `x-show="open"`, `x-if="visible"`
   - Do NOT use `x-model` — use `:checked`/`:value` + `@change`/`@input` instead


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


## Docker

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
