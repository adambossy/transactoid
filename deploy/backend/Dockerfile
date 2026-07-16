# deploy/backend/Dockerfile — multistage uv build of the Penny FastAPI service.
#
# Build context is the REPO ROOT (so the build can see both deploy/ and the
# app tree); paths below are relative to the repo root:
#
#   fly deploy --config deploy/backend/fly.toml \
#              --dockerfile deploy/backend/Dockerfile
#
# The repo is a uv workspace (root pyproject.toml + uv.lock): backend,
# sandbox, and lib resolve/lock together, and the root uv.lock pins
# agent-harness / promptorium-python to their git refs (not a local path), so
# `uv sync --frozen` installs the exact locked set identically here, in CI,
# and in dev — no divergence. penny-backend's runtime closure includes the
# penny-lib workspace member (lib/protocol, the sandbox wire codec) and
# NEVER penny-sandbox (dev-only), so the runner stays out of this image.

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

# Workspace + dependency metadata first for layer caching. uv validates every
# member's pyproject when it reads the workspace, so all three are copied even
# though only penny-backend (and its penny-lib dep) gets installed.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/
COPY sandbox/pyproject.toml ./sandbox/
COPY lib/pyproject.toml ./lib/

# Install third-party deps from the frozen lock (git-pinned agent-harness).
# --no-install-workspace so the workspace members' code (copied next) is
# layered separately and dep layers stay cached.
RUN uv sync --frozen --no-dev --no-install-workspace --package penny-backend

# Application source (mirrors what penny imports + the data it reads).
COPY lib/protocol ./lib/protocol
COPY backend/penny ./backend/penny
COPY backend/.prompts ./backend/.prompts
COPY backend/.agent ./backend/.agent
COPY backend/configs ./backend/configs
COPY backend/alembic ./backend/alembic
COPY backend/alembic.ini ./backend/alembic.ini
# Version scripts (alembic.ini version_locations = %(here)s/db/migrations); the
# release step (`penny migrate`) needs these to evolve the Postgres schema.
COPY backend/db/migrations ./backend/db/migrations

# Install the project itself + penny-lib (now that source is present).
RUN uv sync --frozen --no-dev --no-editable --package penny-backend

# =============================================================================
# Stage 2: production
# =============================================================================
FROM python:3.13-slim AS production

# libpq5: psycopg2 runtime. (No build toolchain in the runtime image.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtualenv + application source from the builder. The runtime layout is
# unchanged from before the workspace split: everything at /app, venv beside
# it — only the builder is workspace-shaped.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/backend/penny /app/penny
COPY --from=builder /app/backend/.prompts /app/.prompts
COPY --from=builder /app/backend/.agent /app/.agent
COPY --from=builder /app/backend/configs /app/configs
COPY --from=builder /app/backend/alembic /app/alembic
COPY --from=builder /app/backend/alembic.ini /app/alembic.ini
COPY --from=builder /app/backend/db/migrations /app/db/migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Persistent HTTP service (NOT a one-shot job). Schema bootstrap runs on
# FastAPI startup (penny.api.main:_on_startup -> bootstrap()).
CMD ["uvicorn", "penny.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
