# deploy/backend/Dockerfile — multistage uv build of the Penny FastAPI service.
#
# Build context is the REPO ROOT (so the build can see both deploy/ and the
# app tree); paths below are relative to the repo root:
#
#   fly deploy --config deploy/backend/fly.toml \
#              --dockerfile deploy/backend/Dockerfile
#
# Resolvability: backend/uv.lock pins agent-harness to a local editable path
# (for local dev). That path does not exist in a remote builder, so we sync
# with `--no-sources`, which ignores [tool.uv.sources] and resolves
# agent-harness from the pinned git commit in [project.dependencies]. This is
# the only divergence from local dev; everything else matches the lock.

# =============================================================================
# Stage 1: builder
# =============================================================================
FROM python:3.13-slim AS builder

# git: agent-harness + promptorium-python are git ("direct reference") deps.
# Build toolchain: matplotlib / psycopg2 may need to compile against headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential \
    && rm -rf /var/lib/apt/lists/*

# uv from PyPI (avoids GHCR pull failures in remote builders).
RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency metadata first for layer caching.
COPY backend/pyproject.toml backend/uv.lock ./

# Resolve + install deps WITHOUT the editable agent-harness source.
# --no-sources ignores [tool.uv.sources]; agent-harness then comes from the
# pinned git commit in [project.dependencies]. --no-install-project so the app
# code (copied next) is layered separately and dep layers stay cached.
RUN uv sync --no-sources --no-dev --no-install-project

# Application source (mirrors what penny imports + the data it reads).
COPY backend/penny ./penny
COPY backend/.prompts ./.prompts
COPY backend/.agent ./.agent
COPY backend/configs ./configs
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

# Install the project itself (now that source is present), still no sources.
RUN uv sync --no-sources --no-dev --no-editable

# =============================================================================
# Stage 2: production
# =============================================================================
FROM python:3.13-slim AS production

# libpq5: psycopg2 runtime. (No build toolchain in the runtime image.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtualenv + application source from the builder.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/penny /app/penny
COPY --from=builder /app/.prompts /app/.prompts
COPY --from=builder /app/.agent /app/.agent
COPY --from=builder /app/configs /app/configs
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Persistent HTTP service (NOT a one-shot job). Schema bootstrap runs on
# FastAPI startup (penny.api.main:_on_startup -> bootstrap()).
CMD ["uvicorn", "penny.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
