#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-transactoid}"
CRON_MANAGER_APP="${CRON_MANAGER_APP:-transactoid-cron-manager}"
CRON_MANAGER_DIR="${CRON_MANAGER_DIR:-ops/cron-manager}"
SCHEDULES_SOURCE="${CRON_MANAGER_DIR}/schedules.json"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd fly
require_cmd jq

if [[ ! -f "$SCHEDULES_SOURCE" ]]; then
  echo "Schedules source not found: $SCHEDULES_SOURCE" >&2
  exit 1
fi

# Resolve the latest image from the main app's running machines.
latest_image="$(
  fly machines list --app "$APP_NAME" --json \
    | jq -r 'sort_by(.updated_at) | last | .config.image // empty'
)"

if [[ -z "$latest_image" ]]; then
  echo "Unable to determine latest image for app: $APP_NAME" >&2
  exit 1
fi

echo "Latest image for $APP_NAME: $latest_image"

# Render the image tag into the schedules file in-place for the deploy.
# The cron-manager Dockerfile copies this file into the image.
rendered="$(jq --arg image "$latest_image" 'map(.config.image = $image)' "$SCHEDULES_SOURCE")"
echo "$rendered" > "$SCHEDULES_SOURCE"

# Deploy the cron manager. On startup, its SyncSchedules logic reads
# /usr/local/share/schedules.json, upserts matching entries, and deletes
# any DB entries whose names no longer appear in the file.
echo "Deploying cron manager..."
fly deploy --app "$CRON_MANAGER_APP" --config "$CRON_MANAGER_DIR/fly.toml" \
  --dockerfile "$CRON_MANAGER_DIR/Dockerfile"

# Restore the schedules file so the rendered image tag doesn't get committed.
git checkout -- "$SCHEDULES_SOURCE"

echo "Cron manager synced successfully."
echo "Synced app image: $latest_image"
