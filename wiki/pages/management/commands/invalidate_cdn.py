"""Invalidate CloudFront paths after a deploy or by request.

Used by ``.github/workflows/deploy.yml`` after a successful deploy so
templates/static-asset/Python changes can't serve stale HTML out of
the CDN. Also useful for ad-hoc invalidations from a shell.

Defaults to wiping every cached path (``/*``). The free monthly quota
is 1000 invalidation paths, and ``/*`` counts as one — so a daily
deploy uses ~30 of those a month.
"""

import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from wiki.lib.cloudfront import invalidate_paths


class Command(BaseCommand):
    help = "Submit a CloudFront invalidation."

    def add_arguments(self, parser):
        parser.add_argument(
            "paths",
            nargs="*",
            default=["/*"],
            help="Paths to invalidate. Defaults to ['/*'].",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be invalidated without calling AWS.",
        )

    def handle(self, *args, paths, dry_run, **options):
        if dry_run:
            target = (
                settings.CLOUDFRONT_DISTRIBUTION_ID or "(unset)"
            )
            self.stdout.write(
                f"Would invalidate {paths} on distribution {target}"
            )
            return

        if not settings.CLOUDFRONT_DISTRIBUTION_ID:
            self.stdout.write(
                "CLOUDFRONT_DISTRIBUTION_ID is unset — skipping invalidation."
            )
            return

        try:
            invalidate_paths(paths)
        except Exception as exc:  # pragma: no cover — invalidate_paths swallows boto errors
            self.stderr.write(f"Invalidation failed: {exc}")
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS(f"Invalidated {paths}"))
