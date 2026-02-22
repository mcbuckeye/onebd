"""Scheduler for automated incremental syncs."""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import AppConfig
from .sync import SyncService

logger = logging.getLogger(__name__)


class SyncScheduler:
    """Scheduler for running incremental syncs on a schedule."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.sync_service = SyncService(config)
        self.scheduler = BackgroundScheduler()
        self._is_running = False

    def _run_incremental_sync(self):
        """Run an incremental sync job."""
        logger.info("Starting scheduled incremental sync...")
        try:
            sync_log = self.sync_service.incremental_sync()
            logger.info(
                f"Scheduled sync completed: {sync_log.records_processed} records processed"
            )
        except Exception as e:
            logger.error(f"Scheduled sync failed: {e}")

    def start(self):
        """Start the scheduler."""
        if self._is_running:
            logger.warning("Scheduler is already running")
            return

        # Parse cron schedule
        schedule = self.config.sync_schedule
        logger.info(f"Setting up sync schedule: {schedule}")

        try:
            # Parse cron expression (minute hour day month day_of_week)
            parts = schedule.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
            else:
                # Default to daily at 2 AM
                trigger = CronTrigger(hour=2, minute=0)

            self.scheduler.add_job(
                self._run_incremental_sync,
                trigger=trigger,
                id="incremental_sync",
                name="Incremental Sync",
                replace_existing=True,
            )

            self.scheduler.start()
            self._is_running = True
            logger.info("Scheduler started successfully")

        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise

    def stop(self):
        """Stop the scheduler."""
        if not self._is_running:
            return

        self.scheduler.shutdown(wait=True)
        self._is_running = False
        logger.info("Scheduler stopped")

    def run_now(self):
        """Trigger an immediate incremental sync."""
        logger.info("Triggering immediate incremental sync...")
        self._run_incremental_sync()

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._is_running
