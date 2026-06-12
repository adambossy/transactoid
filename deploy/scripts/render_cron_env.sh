#!/usr/bin/env bash
# render_cron_env.sh — emit the cron job's config.env as a JSON object from
# the single source of truth (deploy/env/deploy.env.template, section 1).
#
# This is what makes the cron model/provider config impossible to drift from
# the backend: both read the SAME template. sync_cron_manager.sh pipes this
# output into each schedules.json entry's .config.env (alongside the resolved
# image + volume id). Only the NON-SECRET section-1 values are emitted;
# secrets are injected separately via `fly secrets set` on the cron app.
#
# Output: a single-line JSON object, e.g.
#   {"PYTHONUNBUFFERED":"1","PENNY_AGENT_PROVIDER":"gemini",...}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${DEPLOY_ENV_TEMPLATE:-$SCRIPT_DIR/../env/deploy.env.template}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}
require_cmd jq

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Env template not found: $TEMPLATE" >&2
  exit 1
fi

# Walk the template; collect KEY=VALUE pairs only within section 1 (the
# NON-SECRET shared runtime values), i.e. between the "1." and "2." section
# banner comments. jq builds the object, splitting each line on the FIRST '='
# so values containing '=' survive.
awk '
  /^# 1\. NON-SECRET/ { in_section = 1; next }
  /^# 2\. SECRETS/    { in_section = 0 }
  in_section && /^[A-Za-z_][A-Za-z0-9_]*=/ { print }
' "$TEMPLATE" \
  | jq -R -s '
      split("\n")
      | map(select(length > 0))
      | map((index("=")) as $i | {(.[0:$i]): (.[$i+1:])})
      | add // {}
    '
