"""Tests for CDN invalidation when pages change."""

from unittest.mock import patch

import pytest
from django.db import transaction


@pytest.fixture
def mock_invalidate():
    with patch("wiki.pages.signals.invalidate_paths") as m:
        yield m


@pytest.mark.django_db(transaction=True)
def test_create_page_invalidates_url_and_parent(
    mock_invalidate, user, sub_directory
):
    from wiki.pages.models import Page

    p = Page.objects.create(
        title="New",
        content="x",
        directory=sub_directory,
        owner=user,
        created_by=user,
        updated_by=user,
    )
    paths = mock_invalidate.call_args.args[0]
    # Both slash-forms of the page URL.
    assert p.get_absolute_url() in paths
    assert f"{p.get_absolute_url()}/" in paths
    # Both slash-forms of the parent directory listing.
    assert "/c/engineering" in paths
    assert "/c/engineering/" in paths


@pytest.mark.django_db(transaction=True)
def test_root_page_invalidates_root_listing(mock_invalidate, user):
    from wiki.pages.models import Page

    Page.objects.create(
        title="Root Page",
        content="x",
        owner=user,
        created_by=user,
        updated_by=user,
    )
    paths = mock_invalidate.call_args.args[0]
    assert "/" in paths


@pytest.mark.django_db(transaction=True)
def test_slug_change_invalidates_old_url(mock_invalidate, page):
    page.title = "Renamed Page"
    page.save()  # title change rebuilds the slug
    paths = mock_invalidate.call_args.args[0]
    # Old URL — both slash-forms.
    assert "/c/getting-started" in paths
    assert "/c/getting-started/" in paths
    # New URL — both slash-forms.
    assert page.get_absolute_url() in paths
    assert f"{page.get_absolute_url()}/" in paths


@pytest.mark.django_db(transaction=True)
def test_directory_move_invalidates_both_listings(
    mock_invalidate, page, sub_directory
):
    page.directory = sub_directory
    page.save()
    paths = mock_invalidate.call_args.args[0]
    # Old (root) parent listing.
    assert "/" in paths
    # New parent listing — both slash-forms.
    assert "/c/engineering" in paths
    assert "/c/engineering/" in paths
    # Old URL — both slash-forms.
    assert "/c/getting-started" in paths
    assert "/c/getting-started/" in paths


@pytest.mark.django_db(transaction=True)
def test_soft_delete_invalidates(mock_invalidate, page, user):
    mock_invalidate.reset_mock()
    page.soft_delete(user)
    assert mock_invalidate.called
    paths = mock_invalidate.call_args.args[0]
    assert page.get_absolute_url() in paths


@pytest.mark.django_db(transaction=True)
def test_rolled_back_save_does_not_invalidate(
    mock_invalidate, user, sub_directory
):
    """transaction.on_commit must hold the invalidation until commit."""
    from wiki.pages.models import Page

    try:
        with transaction.atomic():
            Page.objects.create(
                title="Doomed",
                content="x",
                directory=sub_directory,
                owner=user,
                created_by=user,
                updated_by=user,
            )
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    mock_invalidate.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_atomic_save_defers_invalidation_until_commit(
    mock_invalidate, user, sub_directory
):
    """The success-path counterpart of test_rolled_back_save_does_not_invalidate.

    Asserts that ``invalidate_paths`` is NOT called inside the atomic block,
    but IS called after the block exits cleanly. Prevents a regression that
    moves invalidation out of ``transaction.on_commit``.
    """
    from wiki.pages.models import Page

    with transaction.atomic():
        Page.objects.create(
            title="Saved",
            content="x",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        # Inside the transaction, invalidation must NOT have fired.
        mock_invalidate.assert_not_called()

    # After commit, it fires.
    mock_invalidate.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_no_op_save_skips_old_path(mock_invalidate, page):
    """Saving without a slug or directory change should not include an old URL."""
    mock_invalidate.reset_mock()
    page.content = "Updated body, same path."
    page.save()
    paths = mock_invalidate.call_args.args[0]
    # Same path → URL variants + parent listing only.
    assert paths == {
        page.get_absolute_url(),
        f"{page.get_absolute_url()}/",
        "/",
    }
