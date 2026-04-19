#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-transactoid}"
CRON_MANAGER_APP="${CRON_MANAGER_APP:-transactoid-cron-manager}"
CRON_MANAGER_DIR="${CRON_MANAGER_DIR:-ops/cron-manager}"
SCHEDULES_SOURCE="${CRON_MANAGER_DIR}/schedules.json"
WORKSPACE_VOLUME_NAME="${WORKSPACE_VOLUME_NAME:-transactoid_workspace}"
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

# Ensure the shared workspace volume exists in the target region so the
# cron machines can mount ~/.transactoid (memory/, reports/) persistently.
# Without this, every scheduled run starts with an empty workspace and
# artifacts like budget.md are missing.
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
  echo "  ./scripts/seed_workspace_volume.sh"
else
  echo "Workspace volume '$WORKSPACE_VOLUME_NAME' already present in $WORKSPACE_VOLUME_REGION."
fi

# Resolve the volume id so we can substitute it into schedules.json. The
# Fly Machines API requires the `volume` (id) field on mounts; the `name`
# field is a CLI-only convenience and is rejected by the cron manager.
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

# Render the image tag and workspace volume id into the schedules file
# in-place for the deploy. The cron-manager Dockerfile copies this file
# into the image, and the cron-manager API requires concrete volume ids
# when dispatching machines.
rendered="$(
  jq --arg image "$latest_image" --arg volume_id "$workspace_volume_id" '
    map(
      .config.image = $image
      | if (.config.mounts? // []) | length > 0 then
          .config.mounts |= map(. + {volume: $volume_id} | del(.name))
        else . end
    )
  ' "$SCHEDULES_SOURCE"
)"
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
