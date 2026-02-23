FROM python:3.13 AS build-base

# Install apt dependencies
# caching: https://docs.docker.com/build/cache/optimize/#use-cache-mounts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update --quiet=2 && \
    apt-get install \
    --no-install-recommends \
    --assume-yes \
    --quiet=2 \
    libpq-dev postgresql-client \
    nodejs npm \
    curl git

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1

ARG BUILD_ENV=prod
ARG GIT_SHA=""
ENV GIT_SHA=${GIT_SHA}

FROM build-base AS python-base

WORKDIR /opt/wiki

# uv install dependencies
# Copy lock file if it exists, generate it if not
COPY pyproject.toml .
COPY uv.loc[k] .
ENV \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-extras

# npm install dependencies
COPY package.json ./
COPY package-lock.jso[n] ./
RUN npm install

COPY . .

# Build Tailwind CSS
RUN npm run build

RUN mkdir -p /opt/wiki/wiki/assets/static/

USER root
RUN chmod +x /opt/wiki/docker/django/docker-entrypoint.sh
RUN chown www-data:www-data /opt/wiki/docker/django/docker-entrypoint.sh

USER www-data
ENTRYPOINT ["/bin/sh", "/opt/wiki/docker/django/docker-entrypoint.sh"]
