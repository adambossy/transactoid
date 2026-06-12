#!/usr/bin/env bash
set -euo pipefail

# Sync the Penny cron-manager. Renders the resolved app image, the workspace
# volume id, AND the shared config.env (from deploy/env/deploy.env.template via
# render_cron_env.sh) into schedules.json, deploys the cron-manager with that
# file baked in, then restores the file so the rendered mutation is never
# committed.
#
# Ported from the legacy transactoid pipeline. The new piece is the config.env
# render: schedules.json no longer hand-carries model/provider env, so the
# cron and backend can never disagree.
#
# Run from the repo root.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_NAME="${APP_NAME:-penny}"
CRON_MANAGER_APP="${CRON_MANAGER_APP:-penny-cron-manager}"
CRON_MANAGER_DIR="${CRON_MANAGER_DIR:-deploy/cron-manager}"
SCHEDULES_SOURCE="${CRON_MANAGER_DIR}/schedules.json"
WORKSPACE_VOLUME_NAME="${WORKSPACE_VOLUME_NAME:-penny_workspace}"
WORKSPACE_VOLUME_REGION="${WORKSPACE_VOLUME_REGION:-iad}"
WORKSPACE_VOLUME_SIZE_GB="${WORKSPACE_VOLUME_SIZE_GB:-1}"

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

# Ensure the shared workspace volume exists in the target region so the cron
# machines can mount ~/.transactoid (memory/, reports/) persistently. Without
# this, every scheduled run starts with an empty workspace and artifacts like
# budget.md are missing.
existing_volume_count="$(
  fly volumes list --app "$APP_NAME" --json \
    | jq --arg name "$WORKSPACE_VOLUME_NAME" --arg region "$WORKSPACE_VOLUME_REGION" \
        '[.[] | select(.name == $name and .region == $region)] | length'
)"

if [[ "$existing_volume_count" == "0" ]]; then
  echo "Creating workspace volume '$WORKSPACE_VOLUME_NAME' in $WORKSPACE_VOLUME_REGION..."
  fly volumes create "$WORKSPACE_VOLUME_NAME" \
    --app "$APP_NAME" \
    --region "$WORKSPACE_VOLUME_REGION" \
    --size "$WORKSPACE_VOLUME_SIZE_GB" \
    --yes
  echo "Volume created. Seed it from the workspace repo by running:"
  echo "  ./deploy/scripts/seed_workspace_volume.sh"
else
  echo "Workspace volume '$WORKSPACE_VOLUME_NAME' already present in $WORKSPACE_VOLUME_REGION."
fi

# Resolve the volume id so we can substitute it into schedules.json. The Fly
# Machines API requires the `volume` (id) field on mounts; the `name` field is
# a CLI-only convenience and is rejected by the cron manager.
workspace_volume_id="$(
  fly volumes list --app "$APP_NAME" --json \
    | jq -r --arg name "$WORKSPACE_VOLUME_NAME" --arg region "$WORKSPACE_VOLUME_REGION" \
        '[.[] | select(.name == $name and .region == $region)] | sort_by(.created_at) | last | .id // empty'
)"

if [[ -z "$workspace_volume_id" ]]; then
  echo "Unable to resolve volume id for '$WORKSPACE_VOLUME_NAME' in $WORKSPACE_VOLUME_REGION" >&2
  exit 1
fi

echo "Workspace volume id: $workspace_volume_id"

# Resolve the latest image from the app's release history. We deliberately do
# NOT use `fly machines list | ... .config.image` here: that pool includes
# ephemeral cron machines (auto_destroy=true) whose config snapshots the image
# they launched with, so a cron machine that started moments after a fresh
# `fly deploy` can win the `sort_by(.updated_at) | last` ranking and bind cron
# to an older image. The releases endpoint is the canonical, atomic record of
# the most recently published deploy.
latest_image="$(
  fly releases --app "$APP_NAME" --json \
    | jq -r '
        [.[] | select(.Status == "complete" and .InProgress == false)]
        | sort_by(.CreatedAt) | last | .ImageRef // empty
      '
)"

if [[ -z "$latest_image" ]]; then
  echo "Unable to determine latest image for app: $APP_NAME" >&2
  exit 1
fi

echo "Latest image for $APP_NAME: $latest_image"

# Render the shared config.env from the single-source-of-truth template.
cron_env="$(bash "$SCRIPT_DIR/render_cron_env.sh")"
echo "Rendered cron config.env from deploy/env/deploy.env.template."

# Render the image tag, workspace volume id, AND config.env into the schedules
# file in-place for the deploy. The cron-manager Dockerfile copies this file
# into the image, and the cron-manager API requires concrete volume ids when
# dispatching machines.
rendered="$(
  jq --arg image "$latest_image" \
     --arg volume_id "$workspace_volume_id" \
     --argjson env "$cron_env" '
    map(
      .config.image = $image
      | .config.env = $env
      | if (.config.mounts? // []) | length > 0 then
          .config.mounts |= map(. + {volume: $volume_id} | del(.name))
        else . end
    )
  ' "$SCHEDULES_SOURCE"
)"
echo "$rendered" > "$SCHEDULES_SOURCE"

# Deploy the cron manager. On startup, its SyncSchedules logic reads
# /usr/local/share/schedules.json, upserts matching entries, and deletes any
# DB entries whose names no longer appear in the file.
echo "Deploying cron manager..."
fly deploy --app "$CRON_MANAGER_APP" --config "$CRON_MANAGER_DIR/fly.toml" \
  --dockerfile "$CRON_MANAGER_DIR/Dockerfile"

# Restore the schedules file so the rendered image/env/volume don't get
# committed.
git checkout -- "$SCHEDULES_SOURCE"

echo "Cron manager synced successfully."
echo "Synced app image: $latest_image"
