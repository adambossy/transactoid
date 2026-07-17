#!/usr/bin/env bash
set -euo pipefail

# Sync the Penny cron-manager. Renders each schedule entry's app image + mount
# volume id (resolved PER app_name, so entries targeting different apps — e.g.
# `penny` and `penny-eval` — bind to their own image and volume), plus the
# shared config.env (from deploy/env/deploy.env.template via render_cron_env.sh),
# into schedules.json; deploys the cron-manager with that file baked in; then
# restores the file so the rendered mutation is never committed.
#
# Ported from the legacy transactoid pipeline. The per-app resolution replaced
# the original single-app assumption when the eval moved to its own app.
#
# Run from the repo root.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

CRON_MANAGER_APP="${CRON_MANAGER_APP:-penny-cron-manager}"
CRON_MANAGER_DIR="${CRON_MANAGER_DIR:-deploy/cron-manager}"
SCHEDULES_SOURCE="${CRON_MANAGER_DIR}/schedules.json"
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

# (Image resolution lives in lib.sh::resolve_latest_image — sourced above.)

# Ensure a workspace volume exists on an app (create if missing) and echo its id.
# The Fly Machines API requires the `volume` (id) field on mounts; the `name`
# field is a CLI-only convenience and is rejected by the cron manager.
ensure_volume_id() {
  local app="$1" name="$2"
  local count
  count="$(
    fly volumes list --app "$app" --json \
      | jq --arg n "$name" --arg r "$WORKSPACE_VOLUME_REGION" \
          '[.[] | select(.name == $n and .region == $r)] | length'
  )"
  if [[ "$count" == "0" ]]; then
    echo "Creating volume '$name' on '$app' in $WORKSPACE_VOLUME_REGION..." >&2
    fly volumes create "$name" --app "$app" --region "$WORKSPACE_VOLUME_REGION" \
      --size "$WORKSPACE_VOLUME_SIZE_GB" --yes >&2
    echo "Volume created. Seed it with:" >&2
    echo "  APP_NAME=$app WORKSPACE_VOLUME_NAME=$name ./deploy/scripts/seed_workspace_volume.sh" >&2
  fi
  fly volumes list --app "$app" --json \
    | jq -r --arg n "$name" --arg r "$WORKSPACE_VOLUME_REGION" \
        '[.[] | select(.name == $n and .region == $r)] | sort_by(.created_at) | last | .id // empty'
}

# Build an { "<app>": "<image>" } map over the distinct app_names in the file.
images_json="{}"
while IFS= read -r app; do
  [[ -z "$app" ]] && continue
  img="$(resolve_latest_image "$app")"
  if [[ -z "$img" ]]; then
    echo "Unable to determine latest image for app: $app" >&2
    exit 1
  fi
  echo "Image for $app: $img"
  images_json="$(jq --arg a "$app" --arg i "$img" '. + {($a): $i}' <<<"$images_json")"
done < <(jq -r '[.[].app_name] | unique[]' "$SCHEDULES_SOURCE")

# Build a { "<app>|<volname>": "<volume id>" } map over the distinct mounts.
volumes_json="{}"
while IFS=$'\t' read -r app name; do
  [[ -z "$app" || -z "$name" ]] && continue
  vid="$(ensure_volume_id "$app" "$name")"
  if [[ -z "$vid" ]]; then
    echo "Unable to resolve volume id for '$name' on '$app'" >&2
    exit 1
  fi
  echo "Volume for $app/$name: $vid"
  volumes_json="$(jq --arg k "$app|$name" --arg v "$vid" '. + {($k): $v}' <<<"$volumes_json")"
done < <(jq -r '
  [.[] | {app: .app_name, mounts: (.config.mounts? // [])} | . as $e
    | $e.mounts[] | [$e.app, .name] | @tsv] | unique[]
' "$SCHEDULES_SOURCE")

# Render the shared config.env from the single-source-of-truth template.
cron_env="$(bash "$SCRIPT_DIR/render_cron_env.sh")"
echo "Rendered cron config.env from deploy/env/deploy.env.template."

# Render per-app image, per-mount volume id, AND config.env into the schedules
# file in-place for the deploy.
rendered="$(
  jq --argjson images "$images_json" \
     --argjson volumes "$volumes_json" \
     --argjson env "$cron_env" '
    map(
      . as $e
      | .config.image = $images[$e.app_name]
      | .config.env = $env
      | if (.config.mounts? // []) | length > 0 then
          .config.mounts |= map(
            . + {volume: $volumes[($e.app_name + "|" + .name)]} | del(.name)
          )
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

# Restore the schedules file so the rendered image/env/volume don't get committed.
git checkout -- "$SCHEDULES_SOURCE"

echo "Cron manager synced successfully."
