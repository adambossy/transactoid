#!/usr/bin/env bash
# Deploy the Penny backend Fly app. Run from the repo root (the build context
# must be the repo root so the Dockerfile can COPY from backend/).
set -euo pipefail

BACKEND_APP="${BACKEND_APP:-penny}"
CONFIG="${BACKEND_CONFIG:-deploy/backend/fly.toml}"
DOCKERFILE="${BACKEND_DOCKERFILE:-deploy/backend/Dockerfile}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
require_cmd fly

echo "Deploying backend app '$BACKEND_APP'..."
fly deploy \
  --app "$BACKEND_APP" \
  --config "$CONFIG" \
  --dockerfile "$DOCKERFILE"
echo "Backend deploy complete."
