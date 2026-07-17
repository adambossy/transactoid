#!/usr/bin/env bash
# Shared helpers for the deploy scripts. SOURCE this file, do not execute it:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib.sh"

# Resolve an app's latest published image ref from its release history.
#
# Deliberately NOT `fly machines list | ... .config.image`: that pool includes
# ephemeral cron machines (auto_destroy=true) whose config snapshots the image
# they launched with, so a cron machine that started moments after a fresh
# `fly deploy` can win the ranking and bind to an older image. The releases
# endpoint is the canonical, atomic record of the most recent deploy.
resolve_latest_image() {
  local app="$1"
  fly releases --app "$app" --json \
    | jq -r '
        [.[] | select(.Status == "complete" and .InProgress == false)]
        | sort_by(.CreatedAt) | last | .ImageRef // empty
      '
}
