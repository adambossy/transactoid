# deploy/cron-manager/Dockerfile — the cron-manager app image.
#
# The base is the Fly Cron Manager image (the scheduler that reads
# schedules.json and spawns ephemeral, auto-destroyed job machines). We only
# layer this app's schedules.json on top of it.
#
# IMPORTANT: the FROM digest below is a PLACEHOLDER. The cron-manager image is
# produced by deploying the Fly Cron Manager blueprint to the
# `penny-cron-manager` app once; after that first deploy, pin this FROM to the
# resulting `registry.fly.io/penny-cron-manager:deployment-<...>` digest (the
# legacy pipeline pinned the transactoid-cron-manager digest the same way).
# See deploy/README.md "Fly credentials / secrets".
FROM registry.fly.io/penny-cron-manager:latest

COPY deploy/cron-manager/schedules.json /usr/local/share/schedules.json
