# syntax=docker/dockerfile:1
#
# Build context is the REPO ROOT, not backend/ (see docker-compose.yml /
# push_images.sh's `-f backend/Dockerfile .`) -- this is deliberate so
# scripts/seed_history.py etc. can be baked into the image. The production
# instance never has a git checkout (see deploy/scripts/bootstrap.sh), so
# scripts/ can't be bind-mounted there the way dev's docker-compose.yml
# bind-mounts it for convenience; the image must be self-contained. All COPY
# paths below are therefore relative to the repo root, not this file's
# directory.
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/
WORKDIR /app

FROM base AS deps
COPY backend/pyproject.toml backend/uv.lock ./
# Dev deps (pytest, ruff) are kept in the image: `make test`/`make lint` run via
# `docker compose exec backend ...` against this same running container.
RUN uv sync --frozen --no-install-project

FROM deps AS runtime
ENV PATH="/app/.venv/bin:${PATH}"
COPY backend/app ./app
COPY backend/tests ./tests
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/docker-entrypoint.sh ./
COPY scripts ./scripts
RUN uv sync --frozen && chmod +x docker-entrypoint.sh

# UID/GID 1000 (not an auto-picked --system id) deliberately matches the
# common single-user Linux/macOS/WSL host default: docker-compose.yml bind-
# mounts host ./data and ./scripts into this container, and a bind mount's
# permissions are enforced by the numeric UID/GID on both sides, not by name.
# A --system-assigned id here (e.g. 999) silently can't write into a host
# directory owned by the host's normal uid-1000 user, which is exactly the
# real bug hit while building Phase 6's live pipeline (PermissionError on
# `data/uploads` the first time an application was actually submitted through
# the running container, not caught by any unit/integration test since those
# never write through the bind mount). Production never hits this at all
# (STORAGE_BACKEND=s3 -> S3Storage, no local filesystem writes -- see
# docs/deployment.md); this is a dev/demo-only constraint, documented here
# rather than solved with a chmod hack. A host whose primary user is not
# uid/gid 1000 would need to override this build arg -- not needed for the
# documented `docker compose up --build -d` quick start.
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --home /app app \
    && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
