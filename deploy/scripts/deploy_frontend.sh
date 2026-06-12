#!/usr/bin/env bash
# Deploy the Penny frontend Fly app. Run from the repo root.
set -euo pipefail

FRONTEND_APP="${FRONTEND_APP:-penny-frontend}"
CONFIG="${FRONTEND_CONFIG:-deploy/frontend/fly.toml}"
DOCKERFILE="${FRONTEND_DOCKERFILE:-deploy/frontend/Dockerfile}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
require_cmd fly

echo "Deploying frontend app '$FRONTEND_APP'..."
fly deploy \
  --app "$FRONTEND_APP" \
  --config "$CONFIG" \
  --dockerfile "$DOCKERFILE"
echo "Frontend deploy complete."
