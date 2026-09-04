#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Brings up the dev stack a local checkout uses (docker/wiki/docker-compose.yml)
# so the agent can run migrations, management commands and the test suite the
# way CLAUDE.md and .github/workflows/tests.yml describe:
#
#   docker compose exec wiki-django python -m pytest --tb=short -q
#
# It also installs pre-commit so `pre-commit run --all-files` works, matching
# .github/workflows/lint.yml.
#
# Only runs in remote sessions; a local checkout already has its own stack.
#
# The hook runs asynchronously: the session starts right away while the stack
# builds in the background, so the agent is usually already working when this
# finishes. Claude Code discards an async hook's output, so the result is left
# where the agent can look it up (CLAUDE.md tells it to):
#
#   /tmp/wiki-stack-status        one word: "starting", "ready" or "failed"
#   /tmp/wiki-session-start.log   everything this script did; on a failure the
#                                 reason is at the end
#
# Network: a web session sits behind an egress gateway that allows only the
# hosts in the environment's network policy and re-terminates TLS with its own
# CA. That applies to the containers too (their traffic is intercepted the same
# way), and while the host image trusts the gateway's CA the stock images do
# not, so uv, npm and playwright would all fail certificate verification during
# the image build. The hook therefore
#
#   - builds the django images from a copy of their base image with the CA
#     installed, swapped in for the Dockerfile's FROM line with a BuildKit named
#     context (docker/django/Dockerfile itself is untouched), and
#   - mounts the CA into every running container,
#
# through a generated, gitignored docker/wiki/docker-compose.override.yml. This
# is the workaround the sandbox's own proxy notes recommend
# (/root/.ccr/README.md). Nothing here routes around the network policy: a
# host the policy denies stays denied, and the hook names it and stops.
#
# Re-running is cheap: SessionStart also fires on resume, /clear and compaction,
# and if the stack is already up the hook exits at once. A run that overlaps a
# still-building one exits too, rather than starting a second build.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

# Must be the first line of stdout: hands the session back while we keep
# working. Nothing written to stdout or stderr after this reaches Claude Code.
echo '{"async": true, "asyncTimeout": 900000}'

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMPOSE_DIR="$REPO_DIR/docker/wiki"
COMPOSE_MAIN="$COMPOSE_DIR/docker-compose.yml"
COMPOSE_REMOTE="$COMPOSE_DIR/docker-compose.override.yml" # generated below; gitignored
DJANGO_DOCKERFILE="$REPO_DIR/docker/django/Dockerfile"
DJANGO_URL="http://localhost:${DJANGO_HOST_PORT:-8001}/"

HOOK_LOG="/tmp/wiki-session-start.log"
STATUS_FILE="/tmp/wiki-stack-status"
LOCK_FILE="/tmp/wiki-session-start.lock"
DOCKERD_LOG="/tmp/dockerd.log"

# The egress gateway's CA bundle; every tool on the host is already pointed at it.
GATEWAY_CA="/root/.ccr/ca-bundle.crt"
# Where the containers see it, and the variables that make uv, python, curl,
# node and git read it. apt and the system OpenSSL store pick it up through
# update-ca-certificates instead.
CA_IN_CONTAINER="/usr/local/share/ca-certificates/claude-egress-gateway.crt"
CA_ENV_VARS=(SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE PIP_CERT NODE_EXTRA_CA_CERTS GIT_SSL_CAINFO)
# The django images' base image with the CA baked in, built by this hook.
TRUSTED_BASE_TAG="wiki-remote-base:latest"

# Every host the stack needs, with the reason. Docker Hub and GHCR serve
# manifests and blobs from different domains, and the image build itself
# fetches apt packages and playwright browsers, so allowing the registry
# hostnames alone is not enough. (pypi.org and registry.npmjs.org are needed
# too, but the sandbox always allows them.)
REQUIRED_HOSTS=(
    "registry-1.docker.io"                 # docker hub manifests
    "production.cloudfront.docker.com"     # docker hub blobs
    "ghcr.io"                              # ghcr.io/astral-sh/uv manifests
    "pkg-containers.githubusercontent.com" # ghcr.io blobs
    "deb.debian.org"                       # apt, during the image build
    "security.debian.org"                  # apt, during the image build
    "cdn.playwright.dev"                   # playwright browsers (BUILD_ENV=dev)
)

exec >>"$HOOK_LOG" 2>&1

log() { echo "[session-start $(date '+%H:%M:%S')] $*"; }
status() { echo "$1" >"$STATUS_FILE"; }

# Mark the stack unavailable, say why, and stop. Exit 0 on purpose: an async
# hook's exit code is a no-op, and the status file is what the session reads.
fail() {
    log "FAILED: $*"
    log "Django, postgres and the test suite are unavailable in this session; lint still works."
    status failed
    exit 0
}

# One run at a time. SessionStart fires again on resume, /clear and compaction,
# which can overlap a first run that is still building; the newcomer must not
# start a second build or, via the trap below, mark the first one failed.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another run of this hook is still bringing the stack up; leaving it to finish"
    exit 0
fi

# An unexpected failure (set -e tripping, a missing .env.example) must still
# leave a terminal status behind, or a session polling the file waits forever.
trap 'if [ "$(cat "$STATUS_FILE" 2>/dev/null)" = "starting" ]; then
          log "FAILED: exiting unexpectedly; see the lines above"
          status failed
      fi' EXIT

log "==== session start $(date -Is) ===="
status starting

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
# 2. Compose files
#
# The override makes every container trust the egress gateway's CA and builds
# the django images from TRUSTED_BASE_TAG instead of their stock base image.
# It is derived from the real compose file and Dockerfile rather than
# hard-coded, so a renamed service or a bumped base image keeps working.
#
# COMPOSE_FILE then lets `docker compose ...` run from anywhere in the repo,
# and makes every invocation, not just this hook's, pick up the override.
# Written before the slow work below, since the session is already running.
# ---------------------------------------------------------------------------
write_remote_override() {
    local base_image services name kind var
    base_image=$(awk '$1 == "FROM" { print $2; exit }' "$DJANGO_DOCKERFILE")
    if [ -z "$base_image" ]; then
        log "WARNING: no FROM line found in $DJANGO_DOCKERFILE; the image build will not trust the gateway CA"
    fi
    # One "name build|image" line per service in the compose file.
    services=$(docker compose -f "$COMPOSE_MAIN" config --format json |
        python3 -c 'import json, sys
for name, svc in json.load(sys.stdin)["services"].items():
    print(name, "build" if "build" in svc else "image")')
    {
        echo "# Generated by .claude/hooks/session-start.sh for Claude Code on the web."
        echo "# Gitignored, and not for local use. Makes every container trust the sandbox's"
        echo "# egress gateway CA, and builds the django images from $TRUSTED_BASE_TAG"
        echo "# (${base_image:-the Dockerfile base image} plus that CA) in place of their stock base image."
        echo "x-trust-gateway-ca: &trust-gateway-ca"
        echo "  environment:"
        for var in "${CA_ENV_VARS[@]}"; do
            echo "    $var: $CA_IN_CONTAINER"
        done
        echo "  volumes:"
        echo "    - $GATEWAY_CA:$CA_IN_CONTAINER:ro"
        echo "services:"
        while read -r name kind; do
            echo "  $name:"
            echo "    <<: *trust-gateway-ca"
            if [ "$kind" = build ] && [ -n "$base_image" ]; then
                echo "    build:"
                echo "      additional_contexts:"
                echo "        - $base_image=docker-image://$TRUSTED_BASE_TAG"
            fi
        done <<<"$services"
    } >"$COMPOSE_REMOTE"
    log "wrote $COMPOSE_REMOTE"
    TRUSTED_BASE_FROM="$base_image"
}

TRUSTED_BASE_FROM=""
if [ -r "$GATEWAY_CA" ]; then
    write_remote_override
    export COMPOSE_FILE="$COMPOSE_MAIN:$COMPOSE_REMOTE"
else
    log "no egress gateway CA at $GATEWAY_CA; using the compose file as is"
    rm -f "$COMPOSE_REMOTE"
    export COMPOSE_FILE="$COMPOSE_MAIN"
fi

compose_export="export COMPOSE_FILE=$COMPOSE_FILE"
if [ -n "${CLAUDE_ENV_FILE:-}" ] && ! grep -qxF "$compose_export" "$CLAUDE_ENV_FILE" 2>/dev/null; then
    echo "$compose_export" >>"$CLAUDE_ENV_FILE"
fi

# ---------------------------------------------------------------------------
# 3. Docker daemon
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
    fail "the docker daemon did not come up; see $DOCKERD_LOG"
fi

# ---------------------------------------------------------------------------
# 4. Lint tooling (mirrors .github/workflows/lint.yml)
#
# Deliberately ahead of the "already running" check below: a running stack
# says nothing about pre-commit being installed, so ordering it after that
# early exit would leave `pre-commit run --all-files` broken in exactly the
# sessions that skip straight past it. Both steps are no-ops once they have run.
# ---------------------------------------------------------------------------
if ! command -v pre-commit >/dev/null 2>&1; then
    log "installing pre-commit"
    uv tool install --quiet pre-commit || log "WARNING: could not install pre-commit"
fi
if command -v pre-commit >/dev/null 2>&1; then
    (cd "$REPO_DIR" && pre-commit install-hooks) || log "WARNING: could not pre-build pre-commit hook environments"
fi

# ---------------------------------------------------------------------------
# 5. Already running?
#
# The stack survives resume, /clear and compaction. Nothing below this point
# needs redoing in that case.
# ---------------------------------------------------------------------------
if curl -fs -o /dev/null --max-time 5 "$DJANGO_URL"; then
    log "READY: the stack is already up at $DJANGO_URL"
    status ready
    exit 0
fi

# ---------------------------------------------------------------------------
# 6. Network policy
#
# Every host below is a hard requirement, so if any is denied the build cannot
# succeed and it is better to say so now, precisely, than to let it fail
# part-way. A denied host shows up as a rejected proxy CONNECT, which curl
# reports as a transport error; no -f here, since a registry answering 401 or
# 404 to an anonymous GET / is still reachable.
# ---------------------------------------------------------------------------
log "checking that the network policy allows the hosts the build needs"
blocked=()
for host in "${REQUIRED_HOSTS[@]}"; do
    if ! curl -sS -o /dev/null --max-time 15 "https://$host/" 2>/dev/null; then
        blocked+=("$host")
    fi
done
if [ ${#blocked[@]} -gt 0 ]; then
    log "these hosts are unreachable, most likely denied by the environment's network policy:"
    for host in "${blocked[@]}"; do
        log "    $host"
    done
    log "Allow them, or pick a less restrictive policy, in the environment's network settings:"
    log "https://code.claude.com/docs/en/claude-code-on-the-web"
    fail "the images cannot be pulled or built while those hosts are unreachable"
fi

# ---------------------------------------------------------------------------
# 7. A base image that trusts the egress gateway
#
# The stock base image plus the gateway CA, installed for the system store and
# named by the env vars every build tool reads. The override from step 2 makes
# docker compose use it for the Dockerfile's FROM line.
# ---------------------------------------------------------------------------
if [ -n "$TRUSTED_BASE_FROM" ]; then
    log "building $TRUSTED_BASE_TAG from $TRUSTED_BASE_FROM plus the egress gateway CA"
    build_ctx=$(mktemp -d)
    cp "$GATEWAY_CA" "$build_ctx/ca-bundle.crt"
    {
        echo "FROM $TRUSTED_BASE_FROM"
        echo "COPY ca-bundle.crt $CA_IN_CONTAINER"
        echo "RUN if command -v update-ca-certificates >/dev/null 2>&1; then update-ca-certificates; fi"
        for var in "${CA_ENV_VARS[@]}"; do
            echo "ENV $var=$CA_IN_CONTAINER"
        done
    } >"$build_ctx/Dockerfile"
    if ! docker build -t "$TRUSTED_BASE_TAG" "$build_ctx"; then
        rm -rf "$build_ctx"
        fail "could not build $TRUSTED_BASE_TAG; see the output above"
    fi
    rm -rf "$build_ctx"
fi

# ---------------------------------------------------------------------------
# 8. Start the stack
#
# --build because wiki-django/wiki-daemon are built from docker/django/Dockerfile
# with BUILD_ENV=dev (dev deps + playwright, needed for wiki/tests_browser.py).
# ---------------------------------------------------------------------------
log "starting the wiki stack (this builds the django image on a cold container; several minutes)"
if ! (cd "$COMPOSE_DIR" && docker compose up -d --build); then
    (cd "$COMPOSE_DIR" && docker compose logs --tail=50) || true
    fail "docker compose up failed; see the output above"
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
for _ in $(seq 1 180); do
    if curl -fsS -o /dev/null "$DJANGO_URL"; then
        django_up=true
        break
    fi
    sleep 1
done

(cd "$COMPOSE_DIR" && docker compose ps)

if [ "$django_up" != true ]; then
    (cd "$COMPOSE_DIR" && docker compose logs --tail=50 wiki-django) || true
    fail "django did not answer at $DJANGO_URL within 180s; see the wiki-django logs above"
fi

log "READY: wiki is up at $DJANGO_URL"
log "Run tests with: docker compose exec wiki-django python -m pytest --tb=short -q"
status ready
