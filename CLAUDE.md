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
├── proposals/         # Change proposals workflow
├── subscriptions/     # Page/directory email subscriptions
├── groups/            # Group management
└── settings/          # Django settings (split by concern)
    ├── django.py      # Core Django settings
    ├── project/       # Security, logging
    └── third_party/   # AWS, email, etc.
```


## Coding Rules

1. **Imports**: MUST put imports at the top of the file. NEVER do inline imports except to prevent circular dependency problems.

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

6. **Type hints**: Encouraged for new code but not yet enforced project-wide.

7. **JavaScript vendoring**: MUST vendor all JS libraries locally in `wiki/assets/static-global/js/`.
   NEVER load JS from CDNs at runtime.

8. **Alpine.js (CSP build)**: The project uses `@alpinejs/csp`, which does NOT support inline
   JavaScript expressions in templates. MUST follow these rules:
   - Register all components in `wiki/assets/static-global/js/alpine-components.js` using `Alpine.data()`
   - Use `x-data="componentName"` (not inline objects like `x-data="{ open: false }"`)
   - Use methods for actions: `@click="toggle"` (not `@click="open = !open"`)
   - Use getters for computed values: `x-text="label"` (not `x-text="open ? 'Yes' : 'No'"`)
   - Simple property access works: `x-show="open"`, `x-if="visible"`
   - Do NOT use `x-model` — use `:checked`/`:value` + `@change`/`@input` instead


## Testing

### Running Tests

```bash
# Run all tests
docker exec wiki-django python -m pytest --tb=short -q

# Run tests for a specific app
docker exec wiki-django python -m pytest wiki/pages/tests.py -v

# Run a specific test class
docker exec wiki-django python -m pytest wiki/pages/tests.py::TestClassName -v

# Run a specific test method
docker exec wiki-django python -m pytest wiki/pages/tests.py::TestClassName::test_method -v
```

### Testing Guidelines

- Use pytest with Django's test client (not unittest-style TestCase)
- Fixtures are defined in `wiki/conftest.py` (shared) and per-app test files
- Use `client.force_login(user)` for authenticated requests
- Use `factory-boy` for complex test data


## Docker Commands

```bash
# Run management commands
docker exec wiki-django python manage.py [command]

# Create migrations
docker exec wiki-django python manage.py makemigrations [app_name]

# Apply migrations
docker exec wiki-django python manage.py migrate

# Django shell
docker exec -it wiki-django python manage.py shell
```


## Tailwind CSS

Tailwind is rebuilt automatically by the `wiki-tailwind` Docker container (runs `npm run dev` in watch mode). NEVER run `npm run build` or `npm run dev` manually — Docker handles it. The compiled `tailwind_styles.css` is gitignored.


## Static Files

NEVER run `collectstatic` in dev. Django serves files directly from `static-global/` via `STATICFILES_DIRS`.


## Dependencies

- **Python**: managed via `pyproject.toml` with `uv`. MUST use `uv` for package management, not `pip`.
- **JavaScript**: `package.json` with `npm`
- **Pre-commit**: `.pre-commit-config.yaml` (ruff linter + formatter)
