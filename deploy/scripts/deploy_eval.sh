#!/usr/bin/env bash
# Deploy the penny-eval app by REUSING the penny backend image (one build, two
# apps). Resolves penny's latest published image ref and deploys it to
# penny-eval, then scales to zero (job-only app: the cron-manager spawns the
# per-run ephemeral machine). Run from the repo root, AFTER deploy_backend.sh
# so the image exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

BACKEND_APP="${BACKEND_APP:-penny}"
EVAL_APP="${EVAL_APP:-penny-eval}"
CONFIG="${EVAL_CONFIG:-deploy/eval/fly.toml}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
require_cmd fly
require_cmd jq

# Reuse the backend's latest published image (shared helper — see lib.sh for why
# `fly releases` and not `fly machines list`).
image="$(resolve_latest_image "$BACKEND_APP")"
if [[ -z "$image" ]]; then
  echo "Unable to determine latest image for app: $BACKEND_APP" >&2
  exit 1
fi
echo "Deploying eval app '$EVAL_APP' with $BACKEND_APP image: $image"

fly deploy \
  --app "$EVAL_APP" \
  --config "$CONFIG" \
  --image "$image"

# Job-only app: no machine should run steady-state. The cron-manager creates the
# ephemeral per-run machine on schedule.
fly scale count 0 --app "$EVAL_APP" --yes >/dev/null 2>&1 || true
echo "Eval deploy complete (scaled to zero)."
