"""Single long-running process that runs every AmatoPay background job.

One process, one systemd unit. Each job is just another management command run
on its own interval in its own thread; a crash in one job never stops the
others, and ``SIGTERM`` (what systemd sends on stop/restart) shuts everything
down cleanly.

    python manage.py run_workers                # run everything
    python manage.py run_workers --only process_webhooks,reconcile_gateway
    python manage.py run_workers --exclude process_webhooks
    python manage.py run_workers --once         # one pass of each job, then exit
    python manage.py run_workers --list         # show the configured jobs

The job list is ``settings.AMATOPAY_WORKERS`` — add a job there (or override an
interval) without touching this file.
"""

import logging
import shlex
import signal
import threading
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

logger = logging.getLogger("apps.core.run_workers")

# Fallback if settings.AMATOPAY_WORKERS is missing. Kept in sync with the
# commands each app ships; prefer editing settings over editing this.
DEFAULT_WORKERS = [
    {"name": "process_pending_payments", "command": "process_pending_payments --limit 100", "interval": 15},
    {"name": "reconcile_gateway", "command": "reconcile_gateway --limit 100", "interval": 20},
    {"name": "process_webhooks", "command": "process_webhooks --limit 100", "interval": 10},
]


class Job:
    def __init__(self, spec: dict):
        raw = spec.get("command") or spec.get("name")
        if not raw:
            raise CommandError(f"Worker spec has no 'command' or 'name': {spec!r}")
        parts = shlex.split(raw)
        self.command = parts[0]
        self.args = parts[1:]
        self.name = spec.get("name") or self.command
        self.interval = int(spec.get("interval", 15))
        self.enabled = bool(spec.get("enabled", True))
        if self.interval < 1:
            raise CommandError(f"Worker '{self.name}' interval must be >= 1 second")

    def run_once(self, stdout, style) -> bool:
        started = time.monotonic()
        try:
            call_command(self.command, *self.args)
            return True
        except Exception:
            logger.exception("worker job %r failed", self.name)
            stdout.write(style.ERROR(f"[{self.name}] failed (see logs)"))
            return False
        finally:
            close_old_connections()
            logger.debug("worker job %r finished in %.2fs", self.name, time.monotonic() - started)


class Command(BaseCommand):
    help = "Run all AmatoPay background jobs in one process (for a single systemd unit)."

    def add_arguments(self, parser):
        parser.add_argument("--only", default="", help="Comma-separated job names to run (exclusively).")
        parser.add_argument("--exclude", default="", help="Comma-separated job names to skip.")
        parser.add_argument("--once", action="store_true", help="Run each job once, then exit.")
        parser.add_argument("--list", action="store_true", help="Print the configured jobs and exit.")

    def handle(self, *args, **options):
        jobs = self._select_jobs(options["only"], options["exclude"])

        if options["list"]:
            for job in jobs:
                state = "on" if job.enabled else "off"
                self.stdout.write(f"{job.name:<28} every {job.interval:>4}s  [{state}]  "
                                  f"→ {job.command} {' '.join(job.args)}".rstrip())
            return

        jobs = [j for j in jobs if j.enabled]
        if not jobs:
            raise CommandError("No enabled jobs to run.")

        if options["once"]:
            failures = 0
            for job in jobs:
                self.stdout.write(f"[{job.name}] running…")
                if not job.run_once(self.stdout, self.style):
                    failures += 1
            if failures:
                raise CommandError(f"{failures} job(s) failed")
            self.stdout.write(self.style.SUCCESS("All jobs completed."))
            return

        self._run_forever(jobs)

    # ── internals ────────────────────────────────────────────────────────────

    def _select_jobs(self, only: str, exclude: str) -> list[Job]:
        specs = getattr(settings, "AMATOPAY_WORKERS", None) or DEFAULT_WORKERS
        jobs = [Job(s) for s in specs]

        names = {j.name for j in jobs}
        only_set = {n.strip() for n in only.split(",") if n.strip()}
        exclude_set = {n.strip() for n in exclude.split(",") if n.strip()}
        unknown = (only_set | exclude_set) - names
        if unknown:
            raise CommandError(
                f"Unknown job(s): {', '.join(sorted(unknown))}. "
                f"Known jobs: {', '.join(sorted(names))}"
            )

        if only_set:
            jobs = [j for j in jobs if j.name in only_set]
        if exclude_set:
            jobs = [j for j in jobs if j.name not in exclude_set]
        return jobs

    def _run_forever(self, jobs: list[Job]):
        stop = threading.Event()

        def _handle_signal(signum, _frame):
            self.stdout.write(self.style.WARNING(f"\nReceived signal {signum}; stopping workers…"))
            stop.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        self.stdout.write(self.style.SUCCESS(
            f"Starting {len(jobs)} worker(s): " + ", ".join(j.name for j in jobs)
        ))
        logger.info("run_workers starting: %s", [j.name for j in jobs])

        threads = []
        for i, job in enumerate(jobs):
            t = threading.Thread(
                target=self._loop, args=(job, stop, i * 1.0), name=f"worker:{job.name}", daemon=True,
            )
            t.start()
            threads.append(t)

        try:
            while not stop.wait(1.0):
                if not any(t.is_alive() for t in threads):
                    break
        finally:
            stop.set()
            for t in threads:
                t.join(timeout=30)

        logger.info("run_workers stopped")
        self.stdout.write(self.style.SUCCESS("Workers stopped."))

    def _loop(self, job: Job, stop: threading.Event, initial_delay: float):
        if stop.wait(initial_delay):
            return
        while not stop.is_set():
            job.run_once(self.stdout, self.style)
            stop.wait(job.interval)
