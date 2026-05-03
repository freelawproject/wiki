"""Tests for CDN invalidation when directories change."""

from unittest.mock import patch

import pytest


@pytest.fixture
def mock_invalidate():
    with patch("wiki.directories.signals.invalidate_paths") as m:
        yield m


@pytest.mark.django_db(transaction=True)
def test_create_directory_invalidates_listing(
    mock_invalidate, user, root_directory
):
    from wiki.directories.models import Directory

    d = Directory.objects.create(
        path="ops",
        title="Ops",
        parent=root_directory,
        owner=user,
        created_by=user,
    )
    paths = mock_invalidate.call_args.args[0]
    # Both slash-forms of the new directory listing.
    assert "/c/ops" in paths
    assert "/c/ops/" in paths
    # Parent (root) listing.
    assert "/" in paths
    assert d.path == "ops"


@pytest.mark.django_db(transaction=True)
def test_directory_rename_invalidates_wildcards_and_self(
    mock_invalidate, sub_directory
):
    """A rename changes every descendant URL.

    The wildcard catches descendants but NOT the directory's own URL
    (per AWS docs: ``/c/foo/*`` matches ``/c/foo/x`` but not ``/c/foo``).
    Both forms must be in the invalidation set.
    """
    sub_directory.path = "platform"
    sub_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert "/c/engineering/*" in paths
    assert "/c/engineering" in paths
    assert "/c/platform/*" in paths
    assert "/c/platform" in paths


@pytest.mark.django_db(transaction=True)
def test_directory_move_invalidates_old_parent(
    mock_invalidate, sub_directory, root_directory
):
    """Moving a directory must drop the old parent's listing too — its
    child count just changed."""
    from wiki.directories.models import Directory

    # Create a new parent and move sub_directory under it.
    new_parent = Directory.objects.create(
        path="orgs", title="Orgs", parent=root_directory
    )
    mock_invalidate.reset_mock()

    sub_directory.parent = new_parent
    sub_directory.path = "orgs/engineering"
    sub_directory.save()

    paths = mock_invalidate.call_args.args[0]
    # New parent listing.
    assert "/c/orgs/" in paths
    # OLD parent listing — root, in this case.
    assert "/" in paths


@pytest.mark.django_db(transaction=True)
def test_no_op_directory_save_skips_wildcards(mock_invalidate, sub_directory):
    """Saving without a path change should not include wildcards."""
    mock_invalidate.reset_mock()
    sub_directory.description = "Updated."
    sub_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert not any("*" in p for p in paths)


@pytest.mark.django_db(transaction=True)
def test_root_directory_save_invalidates_root(mock_invalidate, root_directory):
    root_directory.description = "Welcome."
    root_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert "/" in paths
