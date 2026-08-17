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
#
# Runs asynchronously: the session starts immediately while the stack builds in
# the background. Short status lines go to the session itself — stdout of an async
# hook is streamed as progress and handed to the agent as context once the hook
# finishes — while the full transcript goes to /tmp/wiki-session-start.log. The
# state is also a single word in /tmp/wiki-stack-status: "starting", "ready" or
# "failed". Check that file before running anything that needs the containers.
#
# Re-running is cheap: if the stack is already up the hook says so and exits, so
# it costs nothing on resume, /clear or after a compaction.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

# Must be the first line of stdout: hands the session back while we keep working.
echo '{"async": true, "asyncTimeout": 900000}'

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMPOSE_DIR="$REPO_DIR/docker/wiki"
DOCKERD_LOG="/tmp/dockerd.log"
HOOK_LOG="/tmp/wiki-session-start.log"
STATUS_FILE="/tmp/wiki-stack-status"
DJANGO_URL="http://localhost:${DJANGO_HOST_PORT:-8001}/"

# Every host the stack needs, with the reason. Docker Hub and GHCR serve manifests
# and blobs from different domains, and the image build itself fetches apt packages
# and playwright browsers, so allowing the registry hostnames alone is not enough.
REQUIRED_HOSTS=(
    "registry-1.docker.io"                  # docker hub manifests
    "production.cloudfront.docker.com"      # docker hub blobs
    "ghcr.io"                               # ghcr.io/astral-sh/uv manifests
    "pkg-containers.githubusercontent.com"  # ghcr.io blobs
    "deb.debian.org"                        # apt, during the image build
    "security.debian.org"                   # apt, during the image build
    "cdn.playwright.dev"                    # playwright browsers (BUILD_ENV=dev)
)

# fd 3 stays attached to the hook's real stdout, so a handful of short lines reach
# the session. Everything else is verbose and goes to the log, which a session that
# starts before the stack is up can read to see what happened.
exec 3>&1
exec >>"$HOOK_LOG" 2>&1

log() { echo "[session-start] $*"; }
say() { echo "$*" >&3; }
status() { echo "$1" >"$STATUS_FILE"; }

# An unexpected failure (set -e tripping, a missing .env.example) must still leave
# a terminal status behind, or a session polling the file waits forever.
trap 'if [ "$(cat "$STATUS_FILE" 2>/dev/null)" = "starting" ]; then
          status failed
          say "wiki dev stack: FAILED unexpectedly. See $HOOK_LOG."
      fi' EXIT

status starting

# COMPOSE_FILE lets `docker compose ...` run from anywhere in the repo instead of
# only from docker/wiki/. Written before the slow work below, since the session
# is already running by then.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export COMPOSE_FILE=$COMPOSE_DIR/docker-compose.yml" >>"$CLAUDE_ENV_FILE"
fi

# Names which of REQUIRED_HOSTS this session cannot reach. The egress policy denies
# a blocked host by rejecting the CONNECT, which curl reports as a transport error;
# no -f here, since a reachable registry answering 401 for an anonymous GET / is
# still reachable.
report_unreachable_hosts() {
    local host blocked=()
    for host in "${REQUIRED_HOSTS[@]}"; do
        if ! curl -sS -o /dev/null --max-time 15 "https://$host/" 2>/dev/null; then
            blocked+=("$host")
        fi
    done
    if [ ${#blocked[@]} -eq 0 ]; then
        log "every required host answered, so this is not an egress problem"
        return
    fi
    log "unreachable hosts: ${blocked[*]}"
    say "Unreachable hosts, most likely blocked by the network policy: ${blocked[*]}"
    say "Allow them, or pick a less restrictive policy, in the environment's network"
    say "settings: https://code.claude.com/docs/en/claude-code-on-the-web"
}

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
    status failed
    say "wiki dev stack: FAILED, the docker daemon did not start (see $DOCKERD_LOG)."
    say "Django, postgres and the test suite are unavailable in this session."
    exit 0
fi

# ---------------------------------------------------------------------------
# 3. Already running?
#
# SessionStart also fires on resume, /clear and compaction, and the stack
# survives all three. Nothing below this point needs redoing in that case.
# ---------------------------------------------------------------------------
if curl -fsS -o /dev/null --max-time 5 "$DJANGO_URL"; then
    log "the stack is already up; nothing to do"
    status ready
    say "wiki dev stack: already running at $DJANGO_URL"
    say "Run tests with: docker compose exec wiki-django python -m pytest --tb=short -q"
    exit 0
fi

# ---------------------------------------------------------------------------
# 4. Lint tooling (mirrors .github/workflows/lint.yml)
# ---------------------------------------------------------------------------
if ! command -v pre-commit >/dev/null 2>&1; then
    log "installing pre-commit"
    uv tool install --quiet pre-commit || log "WARNING: could not install pre-commit"
fi
if command -v pre-commit >/dev/null 2>&1; then
    (cd "$REPO_DIR" && pre-commit install-hooks) || log "WARNING: could not pre-build pre-commit hook environments"
fi

# ---------------------------------------------------------------------------
# 5. Start the stack
#
# --build because wiki-django/wiki-daemon are built from docker/django/Dockerfile
# with BUILD_ENV=dev (dev deps + playwright, needed for wiki/tests_browser.py).
# ---------------------------------------------------------------------------
log "starting the wiki stack (this builds the django image on a cold container)"
if ! (cd "$COMPOSE_DIR" && docker compose up -d --build); then
    log "ERROR: docker compose up failed. Recent output:"
    (cd "$COMPOSE_DIR" && docker compose logs --tail=50) || true
    status failed
    say "wiki dev stack: FAILED to build or start. Full output in $HOOK_LOG."
    report_unreachable_hosts
    say "Django, postgres and the test suite are unavailable in this session."
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
    if curl -fsS -o /dev/null "$DJANGO_URL"; then
        django_up=true
        break
    fi
    sleep 1
done

(cd "$COMPOSE_DIR" && docker compose ps)

if [ "$django_up" = true ]; then
    log "wiki is up at $DJANGO_URL"
    status ready
    say "wiki dev stack: ready at $DJANGO_URL"
    say "Run tests with: docker compose exec wiki-django python -m pytest --tb=short -q"
else
    log "WARNING: django did not answer within 120s; check 'docker compose logs wiki-django'"
    status failed
    say "wiki dev stack: FAILED, django did not answer within 120s."
    say "Check 'docker compose logs wiki-django' and $HOOK_LOG."
fi
