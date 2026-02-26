"""Daemon that runs periodic tasks on a configurable schedule.

Replaces host-level crontab entries with an in-process loop that runs
as a separate Docker service.
"""

import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from wiki.pages.tasks import sync_page_view_counts, update_search_vectors

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run periodic tasks (view counts, search vectors, cleanup) in a loop."

    def handle(self, *args, **options):
        self._shutdown = False
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        schedule = self._build_schedule()
        self.stdout.write(
            "Daemon started with schedule: "
            + ", ".join(
                f"{name} every {interval}s" for _, interval, name in schedule
            )
        )

        last_run: dict[str, float] = {}
        while not self._shutdown:
            now = time.monotonic()
            for task_fn, interval, name in schedule:
                if now - last_run.get(name, 0) >= interval:
                    self._run_task(task_fn, name)
                    last_run[name] = time.monotonic()
            time.sleep(1)

        self.stdout.write("Daemon shutting down.")

    def _build_schedule(self):
        from wiki.pages.management.commands.cleanup import (
            Command as CleanupCommand,
        )

        cleanup_cmd = CleanupCommand()

        return [
            (
                sync_page_view_counts,
                settings.DAEMON_SYNC_VIEW_COUNTS_INTERVAL,
                "sync_view_counts",
            ),
            (
                update_search_vectors,
                settings.DAEMON_UPDATE_SEARCH_VECTORS_INTERVAL,
                "update_search_vectors",
            ),
            (
                cleanup_cmd.handle,
                settings.DAEMON_CLEANUP_INTERVAL,
                "cleanup",
            ),
        ]

    def _run_task(self, task_fn, name):
        try:
            self.stdout.write(f"Running {name}...")
            task_fn()
            self.stdout.write(f"Finished {name}.")
        except Exception:
            logger.exception("Error running task %s", name)

    def _handle_signal(self, signum, frame):
        self.stdout.write(f"Received signal {signum}, shutting down...")
        self._shutdown = True
