#!/usr/bin/env bash
set -euo pipefail

# Seed the shared penny_workspace Fly volume by cloning the workspace repo so
# scheduled cron machines start with memory/ and reports/ populated
# (budget.md, index.md, merchant-rules.md, ...).
#
# The volume is attached to an ephemeral machine for the copy and then the
# machine is destroyed, releasing the volume back to the cron pool.
#
# Ported from the legacy transactoid pipeline; app/volume defaults renamed to
# the penny topology.

APP_NAME="${APP_NAME:-penny}"
WORKSPACE_VOLUME_NAME="${WORKSPACE_VOLUME_NAME:-penny_workspace}"
WORKSPACE_VOLUME_REGION="${WORKSPACE_VOLUME_REGION:-iad}"
WORKSPACE_MOUNT_PATH="${WORKSPACE_MOUNT_PATH:-/workspace}"
WORKSPACE_REPO_URL="${WORKSPACE_REPO_URL:-https://github.com/adambossy/transactoid-workspace.git}"
WORKSPACE_REPO_REF="${WORKSPACE_REPO_REF:-main}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd fly
require_cmd jq
require_cmd tar
require_cmd git

clone_dir="$(mktemp -d -t penny-workspace-seed.XXXXXX)"
cleanup_clone() {
  rm -rf "$clone_dir"
}
trap cleanup_clone EXIT

echo "Cloning $WORKSPACE_REPO_URL@$WORKSPACE_REPO_REF into $clone_dir..."
git clone --depth 1 --branch "$WORKSPACE_REPO_REF" "$WORKSPACE_REPO_URL" "$clone_dir"

echo "Picking latest image for $APP_NAME..."
# Use the release history (atomic, canonical) instead of `fly machines list`
# which can return an older image from an ephemeral cron machine that
# launched right after a fresh deploy.
image="$(
  fly releases --app "$APP_NAME" --json \
    | jq -r '
        [.[] | select(.Status == "complete" and .InProgress == false)]
        | sort_by(.CreatedAt) | last | .ImageRef // empty
      '
)"
if [[ -z "$image" ]]; then
  echo "Unable to determine image for app: $APP_NAME" >&2
  exit 1
fi
echo "Using image: $image"

machine_name="penny-seed-$(date -u +%Y%m%d%H%M%S)"
echo "Launching one-off seeder machine '$machine_name' with $WORKSPACE_VOLUME_NAME attached..."
fly machine run "$image" \
  --app "$APP_NAME" \
  --region "$WORKSPACE_VOLUME_REGION" \
  --name "$machine_name" \
  --volume "$WORKSPACE_VOLUME_NAME:$WORKSPACE_MOUNT_PATH" \
  --vm-size shared-cpu-1x \
  --vm-memory 512 \
  --restart no \
  --detach \
  --entrypoint /bin/sh \
  -- -lc 'sleep 900'

machine_id="$(
  fly machines list --app "$APP_NAME" --json \
    | jq -r --arg name "$machine_name" '.[] | select(.name == $name) | .id' \
    | head -n 1
)"
if [[ -z "$machine_id" || "$machine_id" == "null" ]]; then
  echo "Failed to locate seeder machine '$machine_name'." >&2
  exit 1
fi
echo "Seeder machine id: $machine_id"

destroy_machine() {
  echo "Destroying seeder machine $machine_id..."
  fly machine destroy "$machine_id" --app "$APP_NAME" --force >/dev/null || true
  cleanup_clone
}
trap destroy_machine EXIT

echo "Waiting for machine to be running..."
for _ in $(seq 1 60); do
  state="$(fly machines list --app "$APP_NAME" --json | jq -r --arg id "$machine_id" '.[] | select(.id == $id) | .state // empty')"
  if [[ "$state" == "started" ]]; then
    break
  fi
  sleep 2
done
if [[ "$state" != "started" ]]; then
  echo "Machine did not reach 'started' state (last: $state)." >&2
  exit 1
fi

echo "Uploading workspace repo contents to $WORKSPACE_MOUNT_PATH..."
# Stream a tarball over SSH and extract it inside the mount point. This
# preserves permissions and handles nested directories (memory/, reports/).
# The .git directory is included so follow-up pulls from the seeder are
# possible without re-cloning.
tar -C "$clone_dir" -cf - . \
  | fly ssh console --app "$APP_NAME" --machine "$machine_id" \
      -C "/bin/sh -lc 'mkdir -p $WORKSPACE_MOUNT_PATH && tar -C $WORKSPACE_MOUNT_PATH -xf -'"

echo "Seed complete."
