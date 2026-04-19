.PHONY: fly-sync-cron fly-deploy-and-sync-cron fly-seed-workspace

fly-sync-cron:
	./scripts/sync_cron_manager.sh

fly-deploy-and-sync-cron:
	fly deploy --app transactoid
	$(MAKE) fly-sync-cron

fly-seed-workspace:
	./scripts/seed_workspace_volume.sh
