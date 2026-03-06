"""Tests for directory/page path collision prevention."""

import pytest
from django.urls import reverse

from wiki.directories.models import Directory
from wiki.lib.path_utils import (
    directory_path_conflicts_with_page,
    page_path_conflicts_with_directory,
)
from wiki.pages.models import Page


class TestPathConflictHelpers:
    """Unit tests for the collision-detection utilities."""

    def test_page_conflicts_with_existing_directory(
        self, sub_directory, root_directory
    ):
        # sub_directory has path="engineering" under root
        assert page_path_conflicts_with_directory(
            "engineering", root_directory
        )

    def test_page_no_conflict_when_no_directory(self, root_directory):
        assert not page_path_conflicts_with_directory(
            "nonexistent", root_directory
        )

    def test_directory_conflicts_with_existing_page(
        self, page_in_directory, sub_directory
    ):
        # page_in_directory has slug="coding-standards" in dir "engineering"
        assert directory_path_conflicts_with_page(
            "engineering/coding-standards"
        )

    def test_directory_no_conflict_when_no_page(self, root_directory):
        assert not directory_path_conflicts_with_page("nonexistent")

    def test_page_conflict_in_nested_directory(
        self, nested_directory, sub_directory
    ):
        # nested_directory is "engineering/devops"
        assert page_path_conflicts_with_directory("devops", sub_directory)

    def test_page_no_conflict_different_directory(
        self, nested_directory, root_directory
    ):
        # "devops" under root is not "engineering/devops"
        assert not page_path_conflicts_with_directory("devops", root_directory)


class TestPageSlugAvoidsDirectoryCollision:
    """Page.save() should auto-increment the slug to avoid directory paths."""

    def test_slug_incremented_when_directory_exists(
        self, user, root_directory, sub_directory
    ):
        """Creating a page titled 'Engineering' at root should not get
        slug='engineering' since that directory exists."""
        page = Page.objects.create(
            title="Engineering",
            content="test",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        assert page.slug != "engineering"
        assert page.slug == "engineering-2"

    def test_slug_ok_when_no_directory_conflict(self, user, root_directory):
        page = Page.objects.create(
            title="Unique Page",
            content="test",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        assert page.slug == "unique-page"


@pytest.mark.django_db
class TestDirectoryCreateBlocksPageCollision:
    """Creating a directory should be blocked if a page occupies that path."""

    def test_create_directory_where_page_exists(
        self, client, user, sub_directory, page_in_directory
    ):
        """Cannot create directory 'engineering/coding-standards' when a page
        with that slug already exists in 'engineering'."""
        client.force_login(user)
        resp = client.post(
            reverse("directory_create_in_dir", kwargs={"path": "engineering"}),
            {"title": "Coding Standards", "visibility": "public"},
        )
        # Should re-render the form with an error, not redirect
        assert resp.status_code == 200
        assert b"already exists at this path" in resp.content

    def test_create_directory_no_conflict_succeeds(
        self, client, user, sub_directory
    ):
        client.force_login(user)
        resp = client.post(
            reverse("directory_create_in_dir", kwargs={"path": "engineering"}),
            {"title": "New Dir", "visibility": "public"},
        )
        assert resp.status_code == 302
        assert Directory.objects.filter(path="engineering/new-dir").exists()


@pytest.mark.django_db
class TestPageMoveBlocksDirectoryCollision:
    """Moving a page should be blocked if a directory occupies the target path."""

    def test_move_page_to_colliding_directory(
        self, client, user, root_directory, sub_directory, page
    ):
        """Cannot move a page with slug 'engineering' into root, because
        directory 'engineering' already exists."""
        # Create a page with slug that matches a directory name
        colliding_page = Page.objects.create(
            title="My Engineering Page",
            slug="engineering",
            content="test",
            directory=sub_directory,  # currently in engineering/
            owner=user,
            created_by=user,
            updated_by=user,
        )
        client.force_login(user)
        resp = client.post(
            reverse(
                "page_move",
                kwargs={"path": f"engineering/{colliding_page.slug}"},
            ),
            # Move to root — but root already has "engineering" directory
            {"directory": ""},
        )
        assert resp.status_code == 200
        assert b"directory already exists" in resp.content


@pytest.mark.django_db
class TestDirectoryMoveBlocksPageCollision:
    """Moving a directory should be blocked if a page occupies the target path."""

    def test_move_directory_to_colliding_page(
        self, client, user, root_directory, sub_directory, nested_directory
    ):
        """Cannot move 'engineering/devops' to root if a page with slug
        'devops' already exists at root."""
        Page.objects.create(
            title="DevOps",
            slug="devops",
            content="test",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        client.force_login(user)
        resp = client.post(
            reverse("directory_move", kwargs={"path": "engineering/devops"}),
            {"parent": root_directory.pk},
        )
        assert resp.status_code == 200
        assert b"already exists at the destination path" in resp.content
        # Directory should NOT have moved
        nested_directory.refresh_from_db()
        assert nested_directory.path == "engineering/devops"
