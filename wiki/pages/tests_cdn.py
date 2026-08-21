"""Tests for CDN invalidation when pages change."""

from unittest.mock import patch

import pytest
from django.db import transaction
from django.urls import reverse

from wiki.pages.models import Page


@pytest.fixture
def mock_invalidate():
    with patch("wiki.pages.signals.invalidate_paths") as m:
        yield m


@pytest.mark.django_db(transaction=True)
def test_create_page_invalidates_url_and_parent(
    mock_invalidate, user, sub_directory
):
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
    assert sub_directory.get_absolute_url() in paths
    assert f"{sub_directory.get_absolute_url()}/" in paths


@pytest.mark.django_db(transaction=True)
def test_root_page_invalidates_root_listing(mock_invalidate, user):
    Page.objects.create(
        title="Root Page",
        content="x",
        owner=user,
        created_by=user,
        updated_by=user,
    )
    paths = mock_invalidate.call_args.args[0]
    assert reverse("root") in paths


@pytest.mark.django_db(transaction=True)
def test_slug_change_invalidates_old_url(mock_invalidate, page):
    old_url = page.get_absolute_url()
    page.title = "Renamed Page"
    page.save()  # title change rebuilds the slug
    paths = mock_invalidate.call_args.args[0]
    # Old URL — both slash-forms.
    assert old_url in paths
    assert f"{old_url}/" in paths
    # New URL — both slash-forms.
    assert page.get_absolute_url() in paths
    assert f"{page.get_absolute_url()}/" in paths


@pytest.mark.django_db(transaction=True)
def test_directory_move_invalidates_both_listings(
    mock_invalidate, page, sub_directory
):
    old_url = page.get_absolute_url()
    page.directory = sub_directory
    page.save()
    paths = mock_invalidate.call_args.args[0]
    # Old (root) parent listing.
    assert reverse("root") in paths
    # New parent listing — both slash-forms.
    assert sub_directory.get_absolute_url() in paths
    assert f"{sub_directory.get_absolute_url()}/" in paths
    # Old URL — both slash-forms.
    assert old_url in paths
    assert f"{old_url}/" in paths


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
        reverse("page_raw_markdown", kwargs={"path": page.content_path}),
        reverse("page_feed", kwargs={"path": page.content_path}),
        reverse("root"),
    }


@pytest.mark.django_db(transaction=True)
def test_save_invalidates_markdown_and_feed_urls(mock_invalidate, page):
    page.content = "changed"
    page.save()
    paths = mock_invalidate.call_args.args[0]
    assert (
        reverse("page_raw_markdown", kwargs={"path": page.content_path})
        in paths
    )
    assert reverse("page_feed", kwargs={"path": page.content_path}) in paths


@pytest.mark.django_db(transaction=True)
def test_move_invalidates_old_feed_url(mock_invalidate, page, sub_directory):
    old_feed = reverse("page_feed", kwargs={"path": page.content_path})
    page.directory = sub_directory
    page.save()
    paths = mock_invalidate.call_args.args[0]
    assert old_feed in paths
    assert reverse("page_feed", kwargs={"path": page.content_path}) in paths


@pytest.mark.django_db(transaction=True)
def test_history_toggle_invalidates_feed_url(mock_invalidate, page):
    """Turning public history off must evict the cached feed."""
    page.history_is_public = False
    page.save(update_fields=["history_is_public"])
    paths = mock_invalidate.call_args.args[0]
    assert reverse("page_feed", kwargs={"path": page.content_path}) in paths


@pytest.mark.django_db(transaction=True)
def test_bulk_move_invalidates_each_page(
    mock_invalidate,
    client,
    user,
    page,
    page_in_nested_directory,
    sub_directory,
):
    """Bulk move must ``.save()`` each page individually.

    A queryset ``.update()`` would relocate pages without firing the
    per-page ``post_save`` CDN-invalidation signal, silently leaving
    stale cached HTML at the old URLs.
    """
    client.force_login(user)
    old_url = page.get_absolute_url()
    old_nested_url = page_in_nested_directory.get_absolute_url()
    mock_invalidate.reset_mock()
    client.post(
        reverse("page_bulk_move"),
        {
            "page_ids": [page.pk, page_in_nested_directory.pk],
            "directory": sub_directory.pk,
            "next": reverse("root"),
        },
    )
    all_paths = []
    for call in mock_invalidate.call_args_list:
        all_paths.extend(call.args[0])
    assert old_url in all_paths
    assert old_nested_url in all_paths


@pytest.mark.django_db(transaction=True)
def test_create_revision_invalidates_feed_url(mock_invalidate, page, user):
    """Creating a revision should invalidate the page's feed URL.

    Revisions can be created without a Page.save() firing (e.g. by a caller
    that writes the page with QuerySet.update()), so a dedicated
    PageRevision signal is needed to purge the feed.
    """
    mock_invalidate.reset_mock()
    with transaction.atomic():
        page.create_revision(user, "Manual revision")
        # Inside the transaction, invalidation must NOT have fired.
        mock_invalidate.assert_not_called()

    # After commit, the feed URL should be invalidated.
    mock_invalidate.assert_called()
    feed_url = reverse("page_feed", kwargs={"path": page.content_path})
    # Check that the feed URL appears in ANY of the calls
    all_paths = []
    for call in mock_invalidate.call_args_list:
        all_paths.extend(call.args[0])
    assert feed_url in all_paths
