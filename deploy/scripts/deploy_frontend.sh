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

# The Clerk publishable key is inlined into the bundle at BUILD time (Vite reads
# VITE_CLERK_PUBLISHABLE_KEY). It is NOT a runtime fly secret — it must be passed
# as a --build-arg here. Omitting it builds a no-Clerk bundle that sends no bearer
# token, which the clerk-mode backend rejects with 401 "missing bearer token" on
# every request. The value is a PUBLIC key; source it from the frontend env (e.g.
# `set -a && source frontend/.env.local && set +a`) before running this script.
build_args=()
if [[ -n "${VITE_CLERK_PUBLISHABLE_KEY:-}" ]]; then
  build_args+=(--build-arg "VITE_CLERK_PUBLISHABLE_KEY=${VITE_CLERK_PUBLISHABLE_KEY}")
else
  echo "WARNING: VITE_CLERK_PUBLISHABLE_KEY is not set — building a NO-CLERK bundle." >&2
  echo "         The clerk-mode backend will 401 every request. Set it and redeploy" >&2
  echo "         unless you intend a dev/no-auth build." >&2
fi

echo "Deploying frontend app '$FRONTEND_APP'..."
fly deploy \
  --app "$FRONTEND_APP" \
  --config "$CONFIG" \
  --dockerfile "$DOCKERFILE" \
  ${build_args[@]+"${build_args[@]}"}
echo "Frontend deploy complete."
