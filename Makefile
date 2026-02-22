.PHONY: fly-sync-cron fly-deploy-and-sync-cron

fly-sync-cron:
	./scripts/sync_cron_manager.sh

fly-deploy-and-sync-cron:
	fly deploy --app transactoid
	$(MAKE) fly-sync-cron
