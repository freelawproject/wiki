"""Tests for CDN invalidation when directories change."""

from unittest.mock import patch

import pytest
from django.urls import reverse

from wiki.directories.models import Directory


@pytest.fixture
def mock_invalidate():
    with patch("wiki.directories.signals.invalidate_paths") as m:
        yield m


@pytest.mark.django_db(transaction=True)
def test_create_directory_invalidates_listing(
    mock_invalidate, user, root_directory
):
    d = Directory.objects.create(
        path="ops",
        title="Ops",
        parent=root_directory,
        owner=user,
        created_by=user,
    )
    paths = mock_invalidate.call_args.args[0]
    # Both slash-forms of the new directory listing.
    assert d.get_absolute_url() in paths
    assert f"{d.get_absolute_url()}/" in paths
    # Parent (root) listing.
    assert root_directory.get_absolute_url() in paths
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
    old_url = sub_directory.get_absolute_url()
    sub_directory.path = "platform"
    sub_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert f"{old_url}/*" in paths
    assert old_url in paths
    assert f"{sub_directory.get_absolute_url()}/*" in paths
    assert sub_directory.get_absolute_url() in paths


@pytest.mark.django_db(transaction=True)
def test_directory_move_invalidates_old_parent(
    mock_invalidate, sub_directory, root_directory
):
    """Moving a directory must drop the old parent's listing too — its
    child count just changed."""
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
    assert f"{new_parent.get_absolute_url()}/" in paths
    # OLD parent listing — root, in this case.
    assert root_directory.get_absolute_url() in paths


@pytest.mark.django_db(transaction=True)
def test_directory_save_always_invalidates_wildcard(
    mock_invalidate, sub_directory
):
    """Every directory save fires the descendant wildcard.

    Directory-level fields (e.g. ``visibility``) cascade to inheriting
    pages whose rows aren't re-saved, so we must always drop their
    cached HTML.
    """
    mock_invalidate.reset_mock()
    sub_directory.description = "Updated."
    sub_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert f"{sub_directory.get_absolute_url()}/*" in paths


@pytest.mark.django_db(transaction=True)
def test_visibility_flip_invalidates_descendant_wildcard(
    mock_invalidate, sub_directory
):
    """Flipping visibility public -> private must drop descendant
    pages from the CDN, even though their rows aren't re-saved.

    Regression test for the privacy leak where inheriting pages stayed
    cached at the edge for up to 30 days after a directory was made
    private.
    """
    assert sub_directory.visibility == Directory.Visibility.PUBLIC
    mock_invalidate.reset_mock()
    sub_directory.visibility = Directory.Visibility.PRIVATE
    sub_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert f"{sub_directory.get_absolute_url()}/*" in paths


@pytest.mark.django_db(transaction=True)
def test_root_directory_save_invalidates_root(mock_invalidate, root_directory):
    root_directory.description = "Welcome."
    root_directory.save()
    paths = mock_invalidate.call_args.args[0]
    assert reverse("root") in paths
