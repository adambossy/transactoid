# Multi-stage Dockerfile for Transactoid sync job
# Uses uv for fast, deterministic dependency installation

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.12-slim AS builder

# Required for Git-based dependencies in uv.lock / pyproject.toml
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv from PyPI to avoid GHCR pull failures in remote builders
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock* ./

# Install dependencies (without dev dependencies)
# Use --frozen if uv.lock exists, otherwise generate it
RUN if [ -f uv.lock ]; then \
        uv sync --frozen --no-dev; \
    else \
        uv sync --no-dev; \
    fi

# Copy source code
COPY src/ src/
COPY models/ models/
COPY .prompts/ .prompts/
COPY prompts/ prompts/
COPY configs/ configs/
COPY scripts/ scripts/
COPY evals/ evals/

# Initialize a git repository in the image so runtime jobs can refresh from origin/main.
RUN git init . \
    && git config user.email "build@transactoid.local" \
    && git config user.name "transactoid-builder" \
    && git add -A \
    && git commit -m "image snapshot" \
    && git remote add origin "https://github.com/adambossy/transactoid.git"

# Install the package
RUN uv pip install --no-deps -e .

# =============================================================================
# Stage 2: Production
# =============================================================================
FROM python:3.12-slim AS production

# Install runtime dependencies (for psycopg2 + git refresh at job start)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --from=builder /app/src /app/src
COPY --from=builder /app/models /app/models
COPY --from=builder /app/.prompts /app/.prompts
COPY --from=builder /app/prompts /app/prompts
COPY --from=builder /app/configs /app/configs
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/evals /app/evals
COPY --from=builder /app/.git /app/.git

# Set PATH to use venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command: run sync first, then report (which sends email by default)
ENTRYPOINT ["/bin/sh", "-lc"]
CMD ["git -C /app fetch --depth=1 origin main && git -C /app checkout -B main FETCH_HEAD && /app/.venv/bin/transactoid sync \"$PLAID_ACCESS_TOKEN\" && /app/.venv/bin/transactoid report"]
