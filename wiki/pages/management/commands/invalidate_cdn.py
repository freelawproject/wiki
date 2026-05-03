"""Invalidate CloudFront paths from a shell.

Defaults to wiping every cached path (``/*``). The free monthly quota
is 1000 invalidation paths, and ``/*`` counts as one.

Note: post-deploy invalidation is handled directly in
``.github/workflows/deploy.yml`` via the AWS CLI, since the deploy
job doesn't have a Python runtime — the workflow doesn't call this
command. This command is for ad-hoc invalidations.
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
            target = settings.CLOUDFRONT_DISTRIBUTION_ID or "(unset)"
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
        except (
            Exception
        ) as exc:  # pragma: no cover — invalidate_paths swallows boto errors
            self.stderr.write(f"Invalidation failed: {exc}")
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS(f"Invalidated {paths}"))
