# deploy/cron-manager/Dockerfile — the cron-manager app image.
#
# The base is the Fly Cron Manager image (the scheduler that reads
# schedules.json and spawns ephemeral, auto-destroyed job machines). We only
# layer this app's schedules.json on top of it.
#
# Bootstrap base: reuse the legacy transactoid-cron-manager's Fly Cron Manager
# scheduler image (the scheduler binary is app-agnostic; only schedules.json
# differs). After penny-cron-manager's first deploy produces its own image,
# re-pin this FROM to `registry.fly.io/penny-cron-manager:deployment-<...>` so
# the app is self-contained and doesn't depend on the legacy app's registry.
FROM registry.fly.io/penny-cron-manager:deployment-01KTYFYXD2CAAM9ET9RA6VHCVY

COPY deploy/cron-manager/schedules.json /usr/local/share/schedules.json
