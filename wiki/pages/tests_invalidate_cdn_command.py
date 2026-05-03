"""Tests for the invalidate_cdn management command."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.pages.management.commands.invalidate_cdn.invalidate_paths")
def test_default_paths(mock_invalidate):
    out = StringIO()
    call_command("invalidate_cdn", stdout=out)
    mock_invalidate.assert_called_once_with(["/*"])
    assert "Invalidated" in out.getvalue()


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.pages.management.commands.invalidate_cdn.invalidate_paths")
def test_custom_paths(mock_invalidate):
    call_command("invalidate_cdn", "/c/foo", "/sitemap.xml")
    mock_invalidate.assert_called_once_with(["/c/foo", "/sitemap.xml"])


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="EXAMPLE123")
@patch("wiki.pages.management.commands.invalidate_cdn.invalidate_paths")
def test_dry_run_does_not_invalidate(mock_invalidate):
    out = StringIO()
    call_command("invalidate_cdn", "--dry-run", stdout=out)
    mock_invalidate.assert_not_called()
    assert "Would invalidate" in out.getvalue()


@override_settings(CLOUDFRONT_DISTRIBUTION_ID="")
@patch("wiki.pages.management.commands.invalidate_cdn.invalidate_paths")
def test_unset_distribution_skips_cleanly(mock_invalidate):
    out = StringIO()
    call_command("invalidate_cdn", stdout=out)
    mock_invalidate.assert_not_called()
    assert "skipping invalidation" in out.getvalue()
