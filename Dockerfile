# syntax=docker/dockerfile:1
#
# Multi-stage build for the REIM API and CLI.
# The runtime stage carries no build toolchain and runs as a non-root user.

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependency metadata first so the layer caches across source-only changes.
COPY pyproject.toml README.md ./
COPY reim/__init__.py reim/__init__.py
RUN pip install --upgrade pip setuptools wheel && pip install .

COPY reim/ reim/
COPY apps/ apps/
RUN pip install --no-deps .


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    REIM_ENVIRONMENT=production \
    REIM_LOG_JSON=true \
    REIM_CATALOG_PATH=/app/sources/catalog.yml \
    REIM_QUALITY_RULES_PATH=/app/sources/quality_rules.yml

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 reim

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=reim:reim alembic.ini ./
COPY --chown=reim:reim alembic/ alembic/
COPY --chown=reim:reim sources/ sources/
COPY --chown=reim:reim reim/ reim/
COPY --chown=reim:reim apps/ apps/

USER reim
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

# --no-proxy-headers: uvicorn's own ProxyHeadersMiddleware is enabled by
# default and trusts 127.0.0.1, so it can rewrite the client address from a
# caller-supplied X-Forwarded-For header before REIM ever sees the request.
# Measured, six cells: that rewrite happens only when uvicorn's immediate TCP
# peer is itself trusted. It is not, in any containerised topology this repo
# ships — deploy/docker-compose.prod.yml overrides this CMD entirely, and
# there the peer is Caddy on the compose network, so the flag changes nothing
# observable. This CMD governs the case the measurement found the flag does
# bite: a bare `podman run` of this image, or any invocation whose peer really
# is 127.0.0.1. That case is exactly why the flag stays. Beyond it,
# REIM_TRUSTED_PROXY_HOPS is the one place the identity decision belongs, and
# two implementations of it means the stricter one does not hold.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
