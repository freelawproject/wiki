#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Brings up the same dev stack a local checkout uses (docker/wiki/docker-compose.yml)
# so the agent can run migrations, management commands and the test suite exactly
# the way CLAUDE.md and .github/workflows/tests.yml describe:
#
#   docker compose exec wiki-django python -m pytest --tb=short -q
#
# It also installs pre-commit so `pre-commit run --all-files` works, matching
# .github/workflows/lint.yml.
#
# Runs only in remote sessions; a local checkout already has its own stack.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMPOSE_DIR="$REPO_DIR/docker/wiki"
DOCKERD_LOG="/tmp/dockerd.log"

log() { echo "[session-start] $*"; }

# ---------------------------------------------------------------------------
# 1. Environment file
#
# docker-compose.yml reads ../../.env.dev via env_file, so the stack will not
# start without it. Same recipe as the tests workflow: copy .env.example, then
# add CI-safe values. Later keys in the file win, so appending is enough.
# ---------------------------------------------------------------------------
if [ ! -f "$REPO_DIR/.env.dev" ]; then
    log "creating .env.dev from .env.example"
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env.dev"
    {
        echo ""
        echo "# Added by .claude/hooks/session-start.sh"
        echo "SECRET_KEY=insecure-key-for-remote-claude-sessions"
        echo "ALLOWED_HOSTS=*"
    } >>"$REPO_DIR/.env.dev"
fi

# ---------------------------------------------------------------------------
# 2. Docker daemon
#
# The remote image ships the docker CLI but nothing starts dockerd for us.
# ---------------------------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
    log "starting the docker daemon"
    dockerd >"$DOCKERD_LOG" 2>&1 &
    for _ in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
fi

if ! docker info >/dev/null 2>&1; then
    log "ERROR: the docker daemon did not come up; see $DOCKERD_LOG"
    log "The wiki stack is NOT running. Django, postgres and the tests are unavailable."
    exit 0
fi

# ---------------------------------------------------------------------------
# 3. Lint tooling (mirrors .github/workflows/lint.yml)
# ---------------------------------------------------------------------------
if ! command -v pre-commit >/dev/null 2>&1; then
    log "installing pre-commit"
    uv tool install --quiet pre-commit || log "WARNING: could not install pre-commit"
fi
if command -v pre-commit >/dev/null 2>&1; then
    (cd "$REPO_DIR" && pre-commit install-hooks) || log "WARNING: could not pre-build pre-commit hook environments"
fi

# ---------------------------------------------------------------------------
# 4. Start the stack
#
# --build because wiki-django/wiki-daemon are built from docker/django/Dockerfile
# with BUILD_ENV=dev (dev deps + playwright, needed for wiki/tests_browser.py).
# ---------------------------------------------------------------------------
log "starting the wiki stack (this builds the django image on a cold container)"
if ! (cd "$COMPOSE_DIR" && docker compose up -d --build); then
    log "ERROR: docker compose up failed. Recent output:"
    (cd "$COMPOSE_DIR" && docker compose logs --tail=50) || true
    log "If the failure is a 403/Forbidden while pulling images, this session's"
    log "network policy blocks the registry CDNs. Allow docker.io, ghcr.io,"
    log "production.cloudfront.docker.com and pkg-containers.githubusercontent.com"
    log "in the environment's network settings, or use an unrestricted policy:"
    log "https://code.claude.com/docs/en/claude-code-on-the-web"
    log "The wiki stack is NOT running. Django, postgres and the tests are unavailable."
    exit 0
fi

# Wait for postgres, then for Django. wiki-django's entrypoint runs migrate,
# createcachetable and seed_help_pages before runserver, so it is a while
# before the port answers.
log "waiting for postgres"
if ! (cd "$COMPOSE_DIR" && timeout 60 bash -c 'until docker compose exec -T wiki-postgres pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done'); then
    log "WARNING: postgres did not report ready within 60s"
fi

log "waiting for django"
django_up=false
for _ in $(seq 1 120); do
    if curl -fsS -o /dev/null "http://localhost:${DJANGO_HOST_PORT:-8001}/"; then
        django_up=true
        break
    fi
    sleep 1
done

if [ "$django_up" = true ]; then
    log "wiki is up at http://localhost:${DJANGO_HOST_PORT:-8001}/"
else
    log "WARNING: django did not answer within 120s; check 'docker compose logs wiki-django'"
fi

# ---------------------------------------------------------------------------
# 5. Session environment
#
# COMPOSE_FILE lets `docker compose ...` run from anywhere in the repo instead
# of only from docker/wiki/.
# ---------------------------------------------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export COMPOSE_FILE=$COMPOSE_DIR/docker-compose.yml" >>"$CLAUDE_ENV_FILE"
fi

(cd "$COMPOSE_DIR" && docker compose ps)
log "run tests with: docker compose exec wiki-django python -m pytest --tb=short -q"
