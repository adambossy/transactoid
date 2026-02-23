#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-transactoid}"
CRON_MANAGER_APP="${CRON_MANAGER_APP:-transactoid-cron-manager}"
SCHEDULES_SOURCE="${SCHEDULES_SOURCE:-ops/cron-manager/schedules.json}"
REMOTE_SCHEDULES_PATH="${REMOTE_SCHEDULES_PATH:-/data/schedules.json}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd fly
require_cmd jq
require_cmd base64
require_cmd diff
require_cmd mktemp

if [[ ! -f "$SCHEDULES_SOURCE" ]]; then
  echo "Schedules source not found: $SCHEDULES_SOURCE" >&2
  exit 1
fi

latest_image="$(
  fly machines list --app "$APP_NAME" --json \
    | jq -r 'sort_by(.updated_at) | last | .config.image // empty'
)"

if [[ -z "$latest_image" ]]; then
  echo "Unable to determine latest image for app: $APP_NAME" >&2
  exit 1
fi

echo "Latest image for $APP_NAME: $latest_image"

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

rendered_path="$tmp_dir/schedules.rendered.json"
remote_path="$tmp_dir/schedules.remote.json"
remote_normalized_path="$tmp_dir/schedules.remote.normalized.json"
rendered_normalized_path="$tmp_dir/schedules.rendered.normalized.json"

jq --arg image "$latest_image" 'map(.config.image = $image)' "$SCHEDULES_SOURCE" >"$rendered_path"

b64_payload="$(base64 <"$rendered_path" | tr -d '\n')"
fly ssh console --app "$CRON_MANAGER_APP" \
  --command "sh -lc 'printf \"%s\" \"$b64_payload\" | base64 -d > $REMOTE_SCHEDULES_PATH'"

machine_ids="$(fly machines list --app "$CRON_MANAGER_APP" --json | jq -r '.[].id')"
if [[ -z "$machine_ids" ]]; then
  echo "No machines found for app: $CRON_MANAGER_APP" >&2
  exit 1
fi

for machine_id in $machine_ids; do
  echo "Restarting cron-manager machine: $machine_id"
  fly machine restart "$machine_id" --app "$CRON_MANAGER_APP" >/dev/null
done

fly ssh console --app "$CRON_MANAGER_APP" --command "cat $REMOTE_SCHEDULES_PATH" >"$remote_path"

jq -S . "$rendered_path" >"$rendered_normalized_path"
jq -S . "$remote_path" >"$remote_normalized_path"

if ! diff -u "$rendered_normalized_path" "$remote_normalized_path" >/dev/null; then
  echo "Remote schedules do not match rendered schedules." >&2
  diff -u "$rendered_normalized_path" "$remote_normalized_path" || true
  exit 1
fi

echo "Cron manager schedules synced successfully."
echo "Synced app image: $latest_image"
