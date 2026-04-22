"""Tests for the pages app: CRUD, history, diff, search, wiki links."""

import io
import json
from datetime import timedelta

import pytest
import time_machine
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image as PILImage

from wiki.directories.models import Directory
from wiki.lib.edit_lock import acquire_lock_for_page
from wiki.lib.markdown import render_markdown, resolve_wiki_links
from wiki.lib.models import EditLock
from wiki.lib.permissions import can_edit_page
from wiki.pages.diff_utils import unified_diff
from wiki.pages.models import (
    FileUpload,
    Page,
    PageLink,
    PagePermission,
    PageRevision,
    PageViewTally,
    PendingUpload,
    SlugRedirect,
)
from wiki.pages.tasks import (
    OPTIMIZE_BATCH_SIZE,
    optimize_images,
    sync_page_view_counts,
    update_search_vectors,
)
from wiki.pages.views import _extract_mentions
from wiki.subscriptions.models import PageSubscription
from wiki.subscriptions.tasks import _get_content_snippet
from wiki.users.models import SystemConfig


@pytest.fixture
def client():
    return Client()


# ── Page CRUD ──────────────────────────────────────────────


class TestPageCreate:
    def test_create_requires_login(self, client, db):
        r = client.get(reverse("page_create"))
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_create_page(self, client, user):
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Test Page",
                "content": "Hello world",
                "visibility": "public",
                "change_message": "First draft",
            },
        )
        assert r.status_code == 302
        page = Page.objects.get(slug="test-page")
        assert page.title == "Test Page"
        assert page.owner == user
        assert page.revisions.count() == 1

    def test_create_auto_generates_slug(self, client, user):
        client.force_login(user)
        client.post(
            reverse("page_create"),
            {
                "title": "My Great Page",
                "content": "",
                "visibility": "public",
                "change_message": "Test",
            },
        )
        assert Page.objects.filter(slug="my-great-page").exists()

    def test_create_auto_subscribes_creator(self, client, user):
        client.force_login(user)
        client.post(
            reverse("page_create"),
            {
                "title": "Subtest",
                "content": "",
                "visibility": "public",
                "change_message": "Test",
            },
        )
        page = Page.objects.get(slug="subtest")
        assert PageSubscription.objects.filter(user=user, page=page).exists()

    def test_create_in_directory(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            reverse(
                "page_create_in_dir",
                kwargs={"path": sub_directory.path},
            ),
            {
                "title": "Deploy Guide",
                "content": "Steps here",
                "visibility": "public",
                "change_message": "Test",
            },
        )
        assert r.status_code == 302
        page = Page.objects.get(slug="deploy-guide")
        assert page.directory == sub_directory

    def test_create_from_root_with_directory_picker(
        self, client, user, sub_directory
    ):
        """POST to /c/new/ with directory_path should accept 'inherit'
        values and place the page in the chosen directory."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Picker Test",
                "content": "Some content",
                "visibility": "inherit",
                "editability": "inherit",
                "in_sitemap": "inherit",
                "in_llms_txt": "inherit",
                "change_message": "Test creation",
                "directory_path": sub_directory.path,
                "directory_titles": "{}",
            },
        )
        assert r.status_code == 302
        page = Page.objects.get(slug="picker-test")
        assert page.directory == sub_directory
        assert page.visibility == "inherit"
        assert page.in_sitemap == "inherit"
        assert page.in_llms_txt == "inherit"

    def test_create_with_new_directory_via_picker(
        self, client, user, sub_directory
    ):
        """POST to /c/new/ with a non-existent subdirectory should
        create the directory and place the page in it."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "New Dir Page",
                "content": "Content here",
                "visibility": "inherit",
                "editability": "inherit",
                "in_sitemap": "inherit",
                "in_llms_txt": "inherit",
                "change_message": "Test creation",
                "directory_path": "engineering/new-team",
                "directory_titles": json.dumps(
                    {"engineering/new-team": "New Team"}
                ),
            },
        )
        assert r.status_code == 302
        page = Page.objects.get(slug="new-dir-page")
        assert page.directory.path == "engineering/new-team"
        assert page.directory.title == "New Team"

    def test_create_from_root_validation_error_preserves_location(
        self, client, user, sub_directory
    ):
        """When form validation fails, the location picker segments
        should be preserved from POST data, not reset to empty."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "",  # Missing title triggers validation error
                "content": "Some content",
                "visibility": "inherit",
                "editability": "inherit",
                "in_sitemap": "inherit",
                "in_llms_txt": "inherit",
                "change_message": "Test creation",
                "directory_path": sub_directory.path,
                "directory_titles": "{}",
            },
        )
        assert r.status_code == 200  # Re-rendered form
        content = r.content.decode()
        assert sub_directory.title in content


class TestPageDetail:
    def test_public_page_visible_to_anon(self, client, page):
        r = client.get(page.get_absolute_url())
        assert r.status_code == 200
        assert b"Getting Started" in r.content

    def test_private_page_hidden_from_anon(self, client, private_page):
        r = client.get(private_page.get_absolute_url())
        assert r.status_code == 404

    def test_private_page_visible_to_owner(self, client, user, private_page):
        client.force_login(user)
        r = client.get(private_page.get_absolute_url())
        assert r.status_code == 200

    def test_private_page_hidden_from_other_user(
        self, client, other_user, private_page
    ):
        client.force_login(other_user)
        r = client.get(private_page.get_absolute_url())
        assert r.status_code == 404

    def test_private_page_visible_to_system_owner(
        self, client, other_user, private_page
    ):
        SystemConfig.objects.create(owner=other_user)
        client.force_login(other_user)
        r = client.get(private_page.get_absolute_url())
        assert r.status_code == 200

    def test_records_page_view_tally(self, client, page):
        assert PageViewTally.objects.count() == 0
        client.get(page.get_absolute_url())
        assert PageViewTally.objects.count() == 1

    def test_breadcrumbs_on_page(self, client, page):
        r = client.get(page.get_absolute_url())
        assert b"Home" in r.content

    def test_breadcrumbs_in_directory(
        self, client, page_in_directory, sub_directory
    ):
        r = client.get(page_in_directory.get_absolute_url())
        assert b"Engineering" in r.content

    def test_breadcrumbs_hide_private_ancestor(
        self, client, other_user, user, root_directory
    ):
        """SECURITY: private ancestor directories must not appear in
        breadcrumbs for users who lack permission."""
        secret = Directory.objects.create(
            path="classified",
            title="Classified",
            parent=root_directory,
            owner=user,
            created_by=user,
            visibility=Directory.Visibility.PRIVATE,
        )
        child = Directory.objects.create(
            path="classified/public-child",
            title="Public Child",
            parent=secret,
            owner=user,
            created_by=user,
            visibility=Directory.Visibility.PUBLIC,
        )
        p = Page.objects.create(
            title="Visible Page",
            slug="visible-page",
            content="hi",
            directory=child,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        PageRevision.objects.create(
            page=p,
            title=p.title,
            content=p.content,
            change_message="init",
            revision_number=1,
            created_by=user,
        )
        client.force_login(other_user)
        r = client.get(p.get_absolute_url())
        assert r.status_code == 200
        assert b"Classified" not in r.content
        assert b"Public Child" in r.content

    def test_subscription_button_for_authenticated(self, client, user, page):
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert b"subscribeToggle" in r.content

    def test_markdown_rendered(self, client, page):
        r = client.get(page.get_absolute_url())
        assert b"<h2" in r.content


class TestPageAbsoluteUrl:
    def test_page_without_directory(self, page):
        assert page.get_absolute_url() == "/c/getting-started"

    def test_page_in_subdirectory(self, page_in_directory, sub_directory):
        assert page_in_directory.get_absolute_url() == (
            f"/c/{sub_directory.path}/{page_in_directory.slug}"
        )

    def test_page_in_root_directory_no_double_slash(
        self, user, root_directory
    ):
        p = Page.objects.create(
            title="Root Page",
            slug="root-page",
            directory=root_directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        assert p.get_absolute_url() == "/c/root-page"
        assert "//" not in p.get_absolute_url()


class TestPageEdit:
    def test_edit_requires_login(self, client, page):
        r = client.get(
            reverse("page_edit", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302

    def test_edit_page(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Updated content",
                "visibility": "public",
                "change_message": "Updated body",
            },
        )
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.content == "Updated content"
        assert page.revisions.count() == 2

    def test_edit_auto_subscribes_editor(self, client, user, page):
        client.force_login(user)
        # Ensure no subscription exists before editing
        PageSubscription.objects.filter(user=user, page=page).delete()
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Updated content",
                "visibility": "public",
                "change_message": "Updated body",
            },
        )
        assert PageSubscription.objects.filter(user=user, page=page).exists()

    def test_edit_creates_slug_redirect(self, client, user, page):
        client.force_login(user)
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started v2",
                "content": page.content,
                "visibility": "public",
                "change_message": "Renamed",
            },
        )
        page.refresh_from_db()
        assert page.slug == "getting-started-v2"
        assert SlugRedirect.objects.filter(old_slug="getting-started").exists()

    def test_non_owner_cannot_edit_without_permission(
        self, client, other_user, page
    ):
        client.force_login(other_user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Hacked",
                "content": "Hacked",
                "visibility": "public",
                "change_message": "Test",
            },
        )
        # Should redirect back (permission denied)
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.title == "Getting Started"

    def test_editor_scripts_and_config(self, client, user, page):
        """Page forms need editor-config, page-config, and both JS files.

        markdown-editor.js auto-init is skipped when page-config exists
        (page-form.js calls initMarkdownEditor itself).  If editor-config
        or page-config is missing, the editor silently won't initialise.
        """
        client.force_login(user)
        urls = [
            reverse("page_create"),
            reverse("page_edit", kwargs={"path": page.content_path}),
        ]
        for url in urls:
            content = client.get(url).content.decode()
            assert 'id="editor-config"' in content, (
                f"{url} missing editor-config"
            )
            assert 'id="page-config"' in content, (
                f"{url} missing page-config — page-form.js needs it "
                f"to call initMarkdownEditor"
            )
            assert "markdown-editor.js" in content, (
                f"{url} missing markdown-editor.js"
            )
            assert "page-form.js" in content, f"{url} missing page-form.js"


class TestPageDelete:
    def test_delete_requires_login(self, client, page):
        r = client.post(
            reverse("page_delete", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_owner_can_delete(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("page_delete", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert not Page.objects.filter(slug="getting-started").exists()

    def test_non_owner_cannot_delete(self, client, other_user, page):
        client.force_login(other_user)
        r = client.post(
            reverse("page_delete", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert Page.objects.filter(slug="getting-started").exists()

    def test_system_owner_can_delete_any(self, client, other_user, page):
        SystemConfig.objects.create(owner=other_user)
        client.force_login(other_user)
        r = client.post(
            reverse("page_delete", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert not Page.objects.filter(slug="getting-started").exists()


# ── History & Diff ─────────────────────────────────────────


class TestPageHistory:
    def test_history_page_loads(self, client, user, page):
        client.force_login(user)
        r = client.get(
            reverse("page_history", kwargs={"path": page.content_path})
        )
        assert r.status_code == 200
        assert b"v1" in r.content

    def test_history_shows_multiple_revisions(self, client, user, page):
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content="Updated",
            change_message="Second edit",
            revision_number=2,
            created_by=user,
        )
        client.force_login(user)
        r = client.get(
            reverse("page_history", kwargs={"path": page.content_path})
        )
        assert b"v1" in r.content
        assert b"v2" in r.content


class TestPageDiff:
    @pytest.fixture
    def two_revisions(self, client, user, page):
        client.force_login(user)
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content="Changed content",
            change_message="Second edit",
            revision_number=2,
            created_by=user,
        )
        return page

    def test_diff_page_loads(self, client, two_revisions):
        r = client.get(
            reverse(
                "page_diff",
                kwargs={
                    "path": two_revisions.content_path,
                    "v1": 1,
                    "v2": 2,
                },
            )
        )
        assert r.status_code == 200

    def test_diff_shows_changes(self, client, two_revisions):
        r = client.get(
            reverse(
                "page_diff",
                kwargs={
                    "path": two_revisions.content_path,
                    "v1": 1,
                    "v2": 2,
                },
            )
        )
        # Word-level highlighting wraps changed segments in <span> tags,
        # so check for the words rather than the full contiguous phrase.
        assert b"Changed" in r.content
        assert b"content" in r.content


class TestPageRevert:
    @pytest.fixture
    def edited_page(self, client, user, page):
        client.force_login(user)
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Edited content",
                "visibility": "public",
                "change_message": "Edited",
            },
        )
        return page

    def test_revert_creates_new_revision(self, client, user, edited_page):
        client.force_login(user)
        r = client.post(
            reverse(
                "page_revert",
                kwargs={
                    "path": edited_page.content_path,
                    "rev_num": 1,
                },
            )
        )
        assert r.status_code == 302
        edited_page.refresh_from_db()
        assert edited_page.content == "## Welcome\n\nHello world."
        assert edited_page.revisions.count() == 3


# ── History Requires Authentication ───────────────────────


class TestHistoryRequiresAuth:
    """Revision history, diff, and revert are staff-only (login required)."""

    def test_history_redirects_anonymous(self, client, page):
        r = client.get(
            reverse("page_history", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_history_visible_to_authenticated(self, client, user, page):
        client.force_login(user)
        r = client.get(
            reverse("page_history", kwargs={"path": page.content_path})
        )
        assert r.status_code == 200

    def test_diff_redirects_anonymous(self, client, user, page):
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content="v2",
            change_message="edit",
            revision_number=2,
            created_by=user,
        )
        r = client.get(
            reverse(
                "page_diff",
                kwargs={"path": page.content_path, "v1": 1, "v2": 2},
            )
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_diff_visible_to_authenticated(self, client, user, page):
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content="v2",
            change_message="edit",
            revision_number=2,
            created_by=user,
        )
        client.force_login(user)
        r = client.get(
            reverse(
                "page_diff",
                kwargs={"path": page.content_path, "v1": 1, "v2": 2},
            )
        )
        assert r.status_code == 200

    def test_history_link_hidden_for_anonymous(self, client, page):
        r = client.get(page.get_absolute_url())
        assert b"History" not in r.content

    def test_history_link_shown_for_authenticated(self, client, user, page):
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert b"History" in r.content


# ── Slug Redirects & URL Resolution ───────────────────────


class TestSlugRedirect:
    def test_old_slug_redirects_to_new(self, client, page):
        SlugRedirect.objects.create(old_slug="old-name", page=page)
        r = client.get(reverse("resolve_path", kwargs={"path": "old-name"}))
        assert r.status_code == 302
        assert r.url == page.get_absolute_url()


class TestResolvePathView:
    def test_resolves_directory(self, client, sub_directory):
        r = client.get(
            reverse("resolve_path", kwargs={"path": sub_directory.path})
        )
        assert r.status_code == 200
        assert b"Engineering" in r.content

    def test_resolves_page(self, client, page):
        r = client.get(page.get_absolute_url())
        assert r.status_code == 200
        assert b"Getting Started" in r.content

    def test_unknown_path_404(self, client, db):
        r = client.get(
            reverse("resolve_path", kwargs={"path": "nonexistent-page"})
        )
        assert r.status_code == 404


# ── HTMX API Endpoints ────────────────────────────────────


class TestPreviewEndpoint:
    def test_preview_returns_rendered_html(self, client, user):
        client.force_login(user)
        r = client.post(
            reverse("page_preview"),
            {"content": "## Hello"},
        )
        assert r.status_code == 200
        assert b"<h2" in r.content

    def test_preview_works_without_login(self, client, db):
        r = client.post(reverse("page_preview"), {"content": "test"})
        assert r.status_code == 200


class TestFileUpload:
    def test_upload_image(self, client, user):
        client.force_login(user)
        img = SimpleUploadedFile(
            "test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"
        )
        r = client.post(reverse("file_upload"), {"file": img})
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "![test.png]" in data["markdown"]

    def test_upload_non_image(self, client, user):
        client.force_login(user)
        doc = SimpleUploadedFile(
            "doc.pdf", b"PDF content", content_type="application/pdf"
        )
        r = client.post(reverse("file_upload"), {"file": doc})
        data = json.loads(r.content)
        assert "[doc.pdf]" in data["markdown"]
        assert "!" not in data["markdown"]

    def test_upload_no_file_returns_400(self, client, user):
        client.force_login(user)
        r = client.post(reverse("file_upload"))
        assert r.status_code == 400

    def test_blocked_extension_rejected(self, client, user):
        """SECURITY: executable file types must be rejected."""
        client.force_login(user)
        for ext in [".exe", ".js", ".sh", ".bat", ".ps1"]:
            f = SimpleUploadedFile(
                f"malicious{ext}",
                b"payload",
                content_type="application/octet-stream",
            )
            r = client.post(reverse("file_upload"), {"file": f})
            assert r.status_code == 400, f"{ext} should be blocked"
            assert b"not allowed" in r.content

    def test_safe_extension_allowed(self, client, user):
        """SECURITY: normal file types should still be accepted."""
        client.force_login(user)
        f = SimpleUploadedFile(
            "notes.txt", b"hello", content_type="text/plain"
        )
        r = client.post(reverse("file_upload"), {"file": f})
        assert r.status_code == 200


class TestPresignUpload:
    """Tests for the presigned S3 upload flow."""

    def _presign(self, client, payload):
        return client.post(
            reverse("presign_upload"),
            json.dumps(payload),
            content_type="application/json",
        )

    def test_presign_returns_url_and_fields(self, client, user, settings):
        """Presign endpoint returns a presigned POST URL and pending ID."""
        settings.AWS_PRIVATE_STORAGE_BUCKET_NAME = "test-bucket"
        client.force_login(user)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "wiki.pages.views.get_s3_client",
                lambda: _mock_s3_client(),
            )
            r = self._presign(
                client,
                {
                    "filename": "photo.png",
                    "content_type": "image/png",
                    "size": 1024,
                },
            )
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "presigned" in data
        assert "url" in data["presigned"]
        assert "fields" in data["presigned"]
        assert "pending_id" in data
        assert PendingUpload.objects.filter(id=data["pending_id"]).exists()

    def test_presign_blocked_extension(self, client, user):
        client.force_login(user)
        r = self._presign(
            client,
            {
                "filename": "malware.exe",
                "content_type": "application/octet-stream",
                "size": 100,
            },
        )
        assert r.status_code == 400
        assert b"not allowed" in r.content

    def test_presign_size_too_large(self, client, user):
        client.force_login(user)
        r = self._presign(
            client,
            {
                "filename": "huge.zip",
                "content_type": "application/zip",
                "size": 2 * 1024**3,
            },
        )
        assert r.status_code == 400

    def test_presign_requires_auth(self, client):
        r = self._presign(
            client,
            {"filename": "test.png", "content_type": "image/png", "size": 100},
        )
        assert r.status_code == 302  # redirect to login

    def test_presign_no_filename(self, client, user):
        client.force_login(user)
        r = self._presign(client, {"content_type": "image/png", "size": 100})
        assert r.status_code == 400


class TestConfirmUpload:
    """Tests for the upload confirmation step."""

    def test_confirm_creates_file_upload(self, client, user, settings):
        settings.AWS_PRIVATE_STORAGE_BUCKET_NAME = "test-bucket"
        client.force_login(user)
        pending = PendingUpload.objects.create(
            s3_key="uploads/2026/03/abc_photo.png",
            original_filename="photo.png",
            content_type="image/png",
            expected_size=1024,
            uploaded_by=user,
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "wiki.pages.views.get_s3_client",
                lambda: _mock_s3_client(),
            )
            r = client.post(
                reverse("confirm_upload"),
                json.dumps({"pending_id": str(pending.id)}),
                content_type="application/json",
            )
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "![photo.png]" in data["markdown"]
        upload = FileUpload.objects.get(
            original_filename="photo.png", uploaded_by=user
        )
        assert upload.file.name == "uploads/2026/03/abc_photo.png"
        assert not PendingUpload.objects.filter(id=pending.id).exists()

    def test_confirm_non_image_returns_link(self, client, user, settings):
        settings.AWS_PRIVATE_STORAGE_BUCKET_NAME = "test-bucket"
        client.force_login(user)
        pending = PendingUpload.objects.create(
            s3_key="uploads/2026/03/abc_report.pdf",
            original_filename="report.pdf",
            content_type="application/pdf",
            expected_size=1024,
            uploaded_by=user,
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "wiki.pages.views.get_s3_client",
                lambda: _mock_s3_client(),
            )
            r = client.post(
                reverse("confirm_upload"),
                json.dumps({"pending_id": str(pending.id)}),
                content_type="application/json",
            )
        data = json.loads(r.content)
        assert "[report.pdf]" in data["markdown"]
        assert "!" not in data["markdown"]

    def test_confirm_wrong_user_rejected(
        self, client, user, other_user, settings
    ):
        settings.AWS_PRIVATE_STORAGE_BUCKET_NAME = "test-bucket"
        pending = PendingUpload.objects.create(
            s3_key="uploads/2026/03/abc_photo.png",
            original_filename="photo.png",
            content_type="image/png",
            expected_size=1024,
            uploaded_by=user,
        )
        client.force_login(other_user)
        r = client.post(
            reverse("confirm_upload"),
            json.dumps({"pending_id": str(pending.id)}),
            content_type="application/json",
        )
        assert r.status_code == 404

    def test_confirm_requires_auth(self, client, user):
        pending = PendingUpload.objects.create(
            s3_key="uploads/2026/03/abc.png",
            original_filename="test.png",
            content_type="image/png",
            expected_size=100,
            uploaded_by=user,
        )
        r = client.post(
            reverse("confirm_upload"),
            json.dumps({"pending_id": str(pending.id)}),
            content_type="application/json",
        )
        assert r.status_code == 302


def _mock_s3_client():
    """Return a mock S3 client for testing presigned upload flow."""

    class MockS3Client:
        def generate_presigned_post(self, **kwargs):
            return {
                "url": "https://test-bucket.s3.amazonaws.com/",
                "fields": {"key": kwargs["Key"], "Content-Type": "image/png"},
            }

        def head_object(self, **kwargs):
            return {"ContentLength": 1024}

        class exceptions:
            class ClientError(Exception):
                pass

    return MockS3Client()


class TestPageSearchAutocomplete:
    def test_search_returns_matches(self, client, user, page):
        client.force_login(user)
        r = client.get(f"{reverse('page_search')}?q=getting")
        assert r.status_code == 200
        assert b"getting-started" in r.content

    def test_search_short_query_returns_empty(self, client, user):
        client.force_login(user)
        r = client.get(f"{reverse('page_search')}?q=g")
        assert r.status_code == 200
        assert r.content == b""

    def test_search_excludes_current_page(self, client, user, page):
        client.force_login(user)
        r = client.get(
            f"{reverse('page_search')}?q=getting&exclude={page.content_path}"
        )
        assert r.status_code == 200
        assert b"getting-started" not in r.content

    def test_search_hides_private_pages(
        self, client, other_user, private_page
    ):
        """SECURITY: private pages must not appear in autocomplete for
        users without permission."""
        client.force_login(other_user)
        r = client.get(f"{reverse('page_search')}?q=secret")
        assert r.status_code == 200
        assert b"secret-notes" not in r.content

    def test_search_shows_private_page_to_owner(
        self, client, user, private_page
    ):
        """The page owner should still see their own private pages."""
        client.force_login(user)
        r = client.get(f"{reverse('page_search')}?q=secret")
        assert b"secret-notes" in r.content

    def test_search_escapes_html_in_title(self, client, user):
        """SECURITY: XSS payloads in page titles must be escaped."""
        Page.objects.create(
            title='<img src=x onerror="alert(1)">',
            slug="xss-test",
            content="test",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.get(f"{reverse('page_search')}?q=onerror")
        # The raw <img> tag must not appear — it should be escaped
        assert b"<img" not in r.content
        assert b"&lt;img" in r.content


class TestFileServePermissions:
    def test_anon_cannot_access_orphaned_file(self, client, user):
        """SECURITY: files not attached to any page require login."""
        f = SimpleUploadedFile("test.txt", b"hello")
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=f,
            original_filename="test.txt",
        )
        r = client.get(
            reverse(
                "file_serve",
                kwargs={"file_id": upload.id, "filename": "test.txt"},
            )
        )
        assert r.status_code == 404

    def test_authenticated_can_access_orphaned_file(self, client, user):
        """Authenticated users can access orphaned files."""
        f = SimpleUploadedFile("test.txt", b"hello")
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=f,
            original_filename="test.txt",
        )
        client.force_login(user)
        r = client.get(
            reverse(
                "file_serve",
                kwargs={"file_id": upload.id, "filename": "test.txt"},
            )
        )
        # 200 in DEBUG mode (FileResponse), 302 in production (S3 redirect)
        assert r.status_code in (200, 302)

    def test_anon_cannot_access_private_page_file(
        self, client, user, private_page
    ):
        """SECURITY: files on private pages need page permission."""
        f = SimpleUploadedFile("secret.txt", b"classified")
        upload = FileUpload.objects.create(
            page=private_page,
            uploaded_by=user,
            file=f,
            original_filename="secret.txt",
        )
        r = client.get(
            reverse(
                "file_serve",
                kwargs={
                    "file_id": upload.id,
                    "filename": "secret.txt",
                },
            )
        )
        assert r.status_code == 404

    def test_other_user_cannot_access_private_page_file(
        self, client, other_user, private_page, user
    ):
        """SECURITY: non-owner cannot access files on private pages."""
        f = SimpleUploadedFile("secret.txt", b"classified")
        upload = FileUpload.objects.create(
            page=private_page,
            uploaded_by=user,
            file=f,
            original_filename="secret.txt",
        )
        client.force_login(other_user)
        r = client.get(
            reverse(
                "file_serve",
                kwargs={
                    "file_id": upload.id,
                    "filename": "secret.txt",
                },
            )
        )
        assert r.status_code == 404


# ── Markdown & Wiki Links ─────────────────────────────────


class TestMarkdownRendering:
    def test_basic_rendering(self):
        html = str(render_markdown("**bold** text"))
        assert "<strong>bold</strong>" in html

    def test_fenced_code_blocks(self):
        md = "```python\nprint('hello')\n```"
        html = str(render_markdown(md))
        assert "print" in html

    def test_tables(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = str(render_markdown(md))
        assert "<table" in html

    def test_toc_generated(self):
        md = "## Section One\n\n## Section Two"
        result = render_markdown(md)
        toc = getattr(result, "toc_html", "")
        assert "Section One" in toc

    def test_script_tag_stripped(self):
        """SECURITY: <script> tags must be removed from rendered output."""
        html = str(render_markdown('<script>alert("xss")</script>'))
        assert "<script>" not in html
        assert "alert" not in html

    def test_onerror_attribute_stripped(self):
        """SECURITY: event handler attributes must be removed."""
        html = str(render_markdown('<img src=x onerror="alert(1)">'))
        assert "onerror" not in html

    def test_javascript_url_stripped(self):
        """SECURITY: javascript: URLs in links must be neutralised."""
        html = str(render_markdown("[click](javascript:alert(1))"))
        assert "javascript:" not in html

    def test_safe_html_preserved(self):
        """Safe markdown features should survive sanitization."""
        md = "**bold** and [link](https://example.com) and `code`"
        html = str(render_markdown(md))
        assert "<strong>bold</strong>" in html
        assert 'href="https://example.com"' in html
        assert "<code>code</code>" in html

    def test_toc_sanitized(self):
        """SECURITY: toc_html should also be sanitized."""
        md = '## <script>alert("xss")</script> Heading'
        result = render_markdown(md)
        toc = result.toc_html
        assert "<script>" not in toc


class TestWikiLinks:
    def test_known_slug_resolved(self, page):
        content = "See #getting-started for info."
        result = resolve_wiki_links(content)
        assert f"[Getting Started]({page.get_absolute_url()})" in result

    def test_unknown_slug_red_link(self, db):
        content = "See #nonexistent for info."
        result = resolve_wiki_links(content)
        assert 'class="text-red-500' in result
        assert "#nonexistent" in result

    def test_redirect_slug_resolved(self, page):
        SlugRedirect.objects.create(old_slug="old-name", page=page)
        content = "See #old-name for info."
        result = resolve_wiki_links(content)
        assert "[Getting Started]" in result

    def test_no_wiki_links_unchanged(self, db):
        content = "Plain text with no links."
        result = resolve_wiki_links(content)
        assert result == content


# ── Diff Utils ─────────────────────────────────────────────


class TestDiffUtils:
    def test_diff_shows_additions(self):
        html = unified_diff("line one", "line one\nline two")
        assert "line two" in html
        assert "green" in html

    def test_diff_shows_deletions(self):
        html = unified_diff("line one\nline two", "line one")
        assert "line two" in html
        assert "red" in html

    def test_identical_content_empty_diff(self):
        html = unified_diff("same", "same")
        assert html == ""


# ── Tasks (cron jobs) ─────────────────────────────────────


class TestSyncViewCounts:
    def test_sync_aggregates_tallies(self, page):
        PageViewTally.objects.create(page=page, count=3)
        PageViewTally.objects.create(page=page, count=5)
        count = sync_page_view_counts()
        assert count == 1
        page.refresh_from_db()
        assert page.view_count == 8
        assert PageViewTally.objects.count() == 0

    def test_sync_no_tallies(self, db):
        count = sync_page_view_counts()
        assert count == 0


class TestUpdateSearchVectors:
    def test_updates_search_vectors(self, page):
        count = update_search_vectors()
        assert count >= 1
        page.refresh_from_db()
        assert page.search_vector is not None


# ── Seed Help Pages ──────────────────────────────────────


class TestSeedHelpPages:
    def test_creates_help_directory(self, owner_user):
        call_command("seed_help_pages")
        assert Directory.objects.filter(path="help").exists()

    def test_creates_help_pages(self, owner_user):
        call_command("seed_help_pages")
        help_dir = Directory.objects.get(path="help")
        assert Page.objects.filter(directory=help_dir).count() == 13

    def test_pages_are_public(self, owner_user):
        call_command("seed_help_pages")
        help_dir = Directory.objects.get(path="help")
        for p in Page.objects.filter(directory=help_dir):
            assert p.visibility == Page.Visibility.PUBLIC

    def test_pages_have_revisions(self, owner_user):
        call_command("seed_help_pages")
        help_dir = Directory.objects.get(path="help")
        for p in Page.objects.filter(directory=help_dir):
            assert p.revisions.count() >= 1

    def test_idempotent(self, owner_user):
        call_command("seed_help_pages")
        call_command("seed_help_pages")
        help_dir = Directory.objects.get(path="help")
        assert Page.objects.filter(directory=help_dir).count() == 13

    def test_help_pages_accessible_via_url(self, client, owner_user):
        call_command("seed_help_pages")
        r = client.get(reverse("resolve_path", kwargs={"path": "help"}))
        assert r.status_code == 200
        assert b"Help" in r.content

    def test_help_page_detail_loads(self, client, owner_user):
        call_command("seed_help_pages")
        r = client.get(
            reverse("resolve_path", kwargs={"path": "help/markdown-syntax"})
        )
        assert r.status_code == 200
        assert b"Markdown Syntax" in r.content

    def test_wiki_links_resolve_between_help_pages(self, owner_user):
        call_command("seed_help_pages")
        page = Page.objects.get(slug="getting-started-guide")
        # The content has #markdown-syntax links
        resolved = resolve_wiki_links(page.content)
        assert "[Markdown Syntax]" in resolved


# ── Change Message Required ──────────────────────────────


class TestChangeMessageRequired:
    def test_edit_rejects_empty_change_message(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Updated",
                "visibility": "public",
                "change_message": "",
            },
        )
        # Should re-render form with error, not redirect
        assert r.status_code == 200
        assert b"This field is required" in r.content

    def test_create_also_rejects_empty_change_message(self, client, user):
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "No Message Page",
                "content": "Hello",
                "visibility": "public",
                "change_message": "",
            },
        )
        assert r.status_code == 200
        assert b"This field is required" in r.content


# ── Page Move ────────────────────────────────────────────


class TestPageMove:
    def test_move_requires_login(self, client, page):
        r = client.get(
            reverse("page_move", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_move_page_to_directory(self, client, user, page, sub_directory):
        client.force_login(user)
        r = client.post(
            reverse("page_move", kwargs={"path": page.content_path}),
            {"directory": sub_directory.pk},
        )
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.directory == sub_directory

    def test_move_page_to_root(
        self, client, user, page_in_directory, sub_directory
    ):
        client.force_login(user)
        r = client.post(
            reverse(
                "page_move",
                kwargs={"path": page_in_directory.content_path},
            ),
            {"directory": ""},
        )
        assert r.status_code == 302
        page_in_directory.refresh_from_db()
        assert page_in_directory.directory is None

    def test_non_editor_cannot_move(self, client, other_user, page):
        client.force_login(other_user)
        r = client.get(
            reverse("page_move", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302


# ── Subscriber Display ───────────────────────────────────


class TestSubscriberDisplay:
    def test_subscribers_visible_to_authenticated(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert b"Watching:" in r.content
        assert b"Alice" in r.content

    def test_subscribers_hidden_from_anon(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        r = client.get(page.get_absolute_url())
        assert b"Watching:" not in r.content


# ── @-Mentions ───────────────────────────────────────────


class TestMentions:
    def test_extract_mentions(self):
        result = _extract_mentions("Hello @mike and @bob!")
        assert "mike" in result
        assert "bob" in result

    def test_extract_no_mentions(self):
        assert _extract_mentions("No mentions here") == []

    def test_mentions_do_not_auto_subscribe(
        self, client, user, other_user, page
    ):
        client.force_login(user)
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Hey @bob check this out",
                "visibility": "public",
                "change_message": "Added mention",
            },
        )
        assert not PageSubscription.objects.filter(
            user=other_user, page=page
        ).exists()

    def test_mention_nonexistent_user_no_error(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Hey @nonexistent check this",
                "visibility": "public",
                "change_message": "Added mention",
            },
        )
        assert r.status_code == 302

    def test_grant_edit_access_on_mention(
        self, client, user, other_user, private_page
    ):
        """Per-user edit access grant via @-mention modal."""

        client.force_login(user)
        client.post(
            reverse(
                "page_edit",
                kwargs={"path": private_page.content_path},
            ),
            {
                "title": "Secret Notes",
                "content": "Hey @bob help me",
                "visibility": "private",
                "change_message": "Added mention",
                "grant_access_bob": "edit",
            },
        )
        assert PagePermission.objects.filter(
            page=private_page,
            user=other_user,
            permission_type="edit",
        ).exists()

    def test_grant_view_access_on_mention(
        self, client, user, other_user, private_page
    ):
        client.force_login(user)
        client.post(
            reverse(
                "page_edit",
                kwargs={"path": private_page.content_path},
            ),
            {
                "title": "Secret Notes",
                "content": "FYI @bob",
                "visibility": "private",
                "change_message": "Added mention",
                "grant_access_bob": "view",
            },
        )
        assert PagePermission.objects.filter(
            page=private_page,
            user=other_user,
            permission_type="view",
        ).exists()


class TestPreviewTabs:
    def test_page_form_no_separate_preview_button(self, client, user, page):
        client.force_login(user)
        urls = [
            reverse("page_create"),
            reverse("page_edit", kwargs={"path": page.content_path}),
        ]
        for url in urls:
            content = client.get(url).content.decode()
            assert 'id="preview-btn"' not in content

    def test_directory_form_no_separate_preview_button(
        self, client, user, root_directory, sub_directory
    ):
        client.force_login(user)
        urls = [
            reverse("directory_create"),
            reverse(
                "directory_edit",
                kwargs={"path": sub_directory.path},
            ),
        ]
        for url in urls:
            content = client.get(url).content.decode()
            assert 'id="preview-btn"' not in content

    def test_preview_api_still_works(self, client, user):
        client.force_login(user)
        r = client.post(reverse("page_preview"), {"content": "## Test"})
        assert r.status_code == 200
        assert b"<h2" in r.content


class TestMentionSnippet:
    def test_get_content_snippet(self):
        content = "Line 1\nLine 2\nHey @bob check\nLine 4\nLine 5"
        snippet = _get_content_snippet(content, "bob")
        assert "@bob" in snippet
        assert "Line 1" in snippet  # 2 lines before
        assert "Line 5" in snippet  # 2 lines after

    def test_snippet_empty_when_no_match(self):
        assert _get_content_snippet("No mention here", "bob") == ""

    def test_mention_email_includes_snippet(
        self, client, user, other_user, page
    ):
        client.force_login(user)
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Line above\nHey @bob check this\nLine below",
                "visibility": "public",
                "change_message": "Added mention",
            },
        )
        mention_emails = [
            m for m in mail.outbox if "mentioned you" in m.subject
        ]
        assert len(mention_emails) == 1
        assert "Hey @bob check this" in mention_emails[0].body
        assert "subscribed" not in mention_emails[0].body.lower()


class TestUserSearchAPI:
    def test_user_search(self, client, user, other_user):
        client.force_login(user)
        r = client.get(f"{reverse('user_search')}?q=bob")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) == 1
        assert data[0]["username"] == "bob"

    def test_user_search_short_query(self, client, user):
        client.force_login(user)
        r = client.get(f"{reverse('user_search')}?q=")
        data = __import__("json").loads(r.content)
        assert data == []

    def test_user_search_excludes_self(self, client, user):
        client.force_login(user)
        r = client.get(f"{reverse('user_search')}?q=alice")
        data = json.loads(r.content)
        usernames = [u["username"] for u in data]
        assert "alice" not in usernames


class TestPagePermissions:
    def test_permissions_requires_login(self, client, page):
        r = client.get(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_permissions_page_loads(self, client, user, page):
        client.force_login(user)
        r = client.get(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 200
        assert b"Permissions" in r.content

    def test_add_user_permission(self, client, user, other_user, page):
        client.force_login(user)
        r = client.post(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            ),
            {
                "target_type": "user",
                "username": "bob",
                "permission_type": "view",
            },
        )
        assert r.status_code == 302
        assert PagePermission.objects.filter(
            page=page,
            user=other_user,
            permission_type="view",
        ).exists()

    def test_add_group_permission(self, client, user, page, group):
        client.force_login(user)
        r = client.post(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            ),
            {
                "target_type": "group",
                "group": group.pk,
                "permission_type": "edit",
            },
        )
        assert r.status_code == 302
        assert PagePermission.objects.filter(
            page=page,
            group=group,
            permission_type="edit",
        ).exists()

    def test_remove_permission(self, client, user, other_user, page):
        perm = PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="edit",
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            ),
            {"remove": perm.pk},
        )
        assert r.status_code == 302
        assert not PagePermission.objects.filter(pk=perm.pk).exists()

    def test_non_editor_cannot_access(self, client, other_user, page):
        client.force_login(other_user)
        r = client.get(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 302

    def test_group_permission_grants_view_on_private_page(
        self, client, other_user, user, group
    ):
        """A user in a group with VIEW on a private page can see it."""

        p = Page.objects.create(
            title="Group Test",
            slug="group-test",
            content="Secret group content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        # Without group membership, other_user can't see it
        client.force_login(other_user)
        r = client.get(p.get_absolute_url())
        assert r.status_code == 404

        # Grant group VIEW permission and add user to group
        PagePermission.objects.create(
            page=p, group=group, permission_type="view"
        )
        other_user.groups.add(group)
        # Clear cached group IDs
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache

        r = client.get(p.get_absolute_url())
        assert r.status_code == 200

    def test_group_edit_permission_allows_editing(
        self, client, other_user, page, group
    ):
        """A user in a group with EDIT permission can edit the page."""

        PagePermission.objects.create(
            page=page, group=group, permission_type="edit"
        )
        other_user.groups.add(group)

        client.force_login(other_user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Getting Started",
                "content": "Group edited",
                "visibility": "public",
                "change_message": "Group edit",
            },
        )
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.content == "Group edited"


class TestPagePeople:
    def test_creator_shown_on_detail(self, client, page):
        r = client.get(page.get_absolute_url())
        assert b"Creator:" in r.content
        assert b"Alice" in r.content

    def test_owner_shown_as_admin(self, client, other_user, user, page):
        """Owner appears as admin when another user views."""

        # Add other_user as OWNER permission (admin)
        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="owner",
        )
        r = client.get(page.get_absolute_url())
        assert b"Admins:" in r.content
        assert b"Bob" in r.content

    def test_editor_permission_shown(self, client, other_user, page):
        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="edit",
        )
        r = client.get(page.get_absolute_url())
        assert b"Editors:" in r.content
        assert b"Bob" in r.content

    def test_admin_not_duplicated_in_editors(self, client, other_user, page):
        """A user with OWNER perm should only appear as admin, not editor."""

        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="owner",
        )
        r = client.get(page.get_absolute_url())
        content = r.content.decode()
        # Bob should be in Admins but not Editors
        assert "Admins:" in content
        # Only one Bob badge should appear (in admins)
        assert content.count("Bob") == 1


class TestCheckMentionPermissions:
    def test_public_page_no_issues(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("check_mention_perms"),
            json.dumps({"page_slug": page.slug, "usernames": ["bob"]}),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert data["users_without_access"] == []

    def test_private_page_flags_user(
        self, client, user, other_user, private_page
    ):
        client.force_login(user)
        r = client.post(
            reverse("check_mention_perms"),
            json.dumps(
                {
                    "page_slug": private_page.slug,
                    "usernames": ["bob"],
                }
            ),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert len(data["users_without_access"]) == 1
        assert data["users_without_access"][0]["username"] == "bob"


class TestPageVisibilityInheritance:
    """Part 3: Page visibility defaults from parent directory."""

    def test_page_create_defaults_to_private_in_private_dir(
        self, client, user, private_directory
    ):
        client.force_login(user)
        r = client.get(
            reverse(
                "page_create_in_dir",
                kwargs={"path": private_directory.path},
            )
        )
        content = r.content.decode()
        # The visibility dropdown should have private selected
        assert "selected" in content
        assert "private" in content

    def test_can_create_public_page_in_private_dir(
        self, client, user, private_directory
    ):
        """Explicit overrides always work — no 'more open than parent' validation."""
        client.force_login(user)
        r = client.post(
            reverse(
                "page_create_in_dir",
                kwargs={"path": private_directory.path},
            ),
            {
                "title": "Public In Private",
                "content": "test",
                "visibility": "public",
                "change_message": "test",
                "directory_path": private_directory.path,
            },
        )
        assert r.status_code == 302
        assert Page.objects.filter(slug="public-in-private").exists()

    def test_can_create_private_page_in_private_dir(
        self, client, user, private_directory
    ):
        client.force_login(user)
        r = client.post(
            reverse(
                "page_create_in_dir",
                kwargs={"path": private_directory.path},
            ),
            {
                "title": "Private In Private",
                "content": "test",
                "visibility": "private",
                "change_message": "test",
                "directory_path": private_directory.path,
            },
        )
        assert r.status_code == 302
        assert Page.objects.filter(slug="private-in-private").exists()

    def test_can_edit_to_public_in_private_dir(
        self, client, user, private_directory
    ):
        """Explicit overrides always work — no 'more open than parent' validation."""
        page = Page.objects.create(
            title="Secret Page",
            slug="secret-page-edit",
            content="test",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message="init",
            revision_number=1,
            created_by=user,
        )
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Secret Page",
                "content": "updated",
                "visibility": "public",
                "change_message": "try public",
                "directory_path": private_directory.path,
            },
        )
        assert r.status_code == 302


class TestCheckPagePermissions:
    """Part 5: Unified permissions endpoint with linked slugs."""

    def test_linked_private_page_flagged(
        self, client, user, page, private_page
    ):
        """A public page linking to a private page gets flagged."""
        client.force_login(user)
        r = client.post(
            reverse("check_page_perms"),
            json.dumps(
                {
                    "page_slug": page.slug,
                    "usernames": [],
                    "linked_slugs": [private_page.slug],
                }
            ),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert len(data["restrictive_links"]) == 1
        assert data["restrictive_links"][0]["slug"] == "secret-notes"

    def test_linked_public_page_not_flagged(self, client, user, page):
        """A public page linking to another public page isn't flagged."""
        Page.objects.create(
            title="Other Public",
            slug="other-public",
            content="hi",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.post(
            reverse("check_page_perms"),
            json.dumps(
                {
                    "page_slug": page.slug,
                    "usernames": [],
                    "linked_slugs": ["other-public"],
                }
            ),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert data["restrictive_links"] == []

    def test_nonexistent_slug_ignored(self, client, user, page):
        """Unknown slugs are silently ignored."""
        client.force_login(user)
        r = client.post(
            reverse("check_page_perms"),
            json.dumps(
                {
                    "page_slug": page.slug,
                    "usernames": [],
                    "linked_slugs": ["no-such-page"],
                }
            ),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert data["restrictive_links"] == []

    def test_combined_mentions_and_links(
        self, client, user, other_user, private_page
    ):
        """Both mentions and links checked in one request."""
        client.force_login(user)
        r = client.post(
            reverse("check_page_perms"),
            json.dumps(
                {
                    "page_slug": private_page.slug,
                    "usernames": ["bob"],
                    "linked_slugs": [],
                }
            ),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert len(data["users_without_access"]) == 1
        assert data["restrictive_links"] == []

    def test_old_endpoint_still_works(self, client, user, page):
        """The old /api/check-mention-perms/ still works."""
        client.force_login(user)
        r = client.post(
            reverse("check_mention_perms"),
            json.dumps(
                {
                    "page_slug": page.slug,
                    "usernames": [],
                }
            ),
            content_type="application/json",
        )
        assert r.status_code == 200


# ── Editability ────────────────────────────────────────────


class TestPageEditability:
    """Tests for the FLP-wide editability setting on pages."""

    def test_default_editability_is_restricted(self, page):
        assert page.editability == "restricted"

    def test_flp_editable_allows_any_authenticated_user(
        self, other_user, page
    ):
        """When editability is 'internal', any logged-in user can edit."""
        assert not can_edit_page(other_user, page)
        page.editability = "internal"
        page.save(update_fields=["editability"])
        assert can_edit_page(other_user, page)

    def test_flp_editable_does_not_allow_anon(self, page):
        """Anonymous users cannot edit even with FLP Staff editability."""
        page.editability = "internal"
        page.save(update_fields=["editability"])
        assert not can_edit_page(AnonymousUser(), page)

    def test_create_page_with_editability(self, client, user):
        """Creating a page with editability='internal' works."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Open Page",
                "content": "Everyone edits",
                "visibility": "public",
                "editability": "internal",
                "change_message": "Created open page",
            },
        )
        assert r.status_code == 302
        p = Page.objects.get(slug="open-page")
        assert p.editability == "internal"

    def test_editability_defaults_to_restricted_when_omitted(
        self, client, user
    ):
        """Omitting editability from POST still creates a page
        with restricted editability (backwards compat)."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Default Edit",
                "content": "",
                "visibility": "public",
                "change_message": "test",
            },
        )
        assert r.status_code == 302
        p = Page.objects.get(slug="default-edit")
        assert p.editability == "restricted"

    def test_can_set_flp_editable_with_private_visibility(self, client, user):
        """Explicit overrides always work — no editability/visibility validation."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Bad Combo",
                "content": "test",
                "visibility": "private",
                "editability": "internal",
                "change_message": "test",
            },
        )
        assert r.status_code == 302
        assert Page.objects.filter(slug="bad-combo").exists()

    def test_can_edit_to_flp_editable_with_private(self, client, user):
        """Explicit overrides always work — no editability/visibility validation."""
        page = Page.objects.create(
            title="Private Edit Test",
            slug="private-edit-test",
            content="test",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message="init",
            revision_number=1,
            created_by=user,
        )
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": "Private Edit Test",
                "content": "updated",
                "visibility": "private",
                "editability": "internal",
                "change_message": "try bad combo",
            },
        )
        assert r.status_code == 302

    def test_form_includes_editability_field(self, client, user):
        """The page form includes the editability dropdown."""
        client.force_login(user)
        r = client.get(reverse("page_create"))
        assert b"id_editability" in r.content

    def test_flp_editable_public_is_valid(self, client, user):
        """FLP Staff editability + Public is a valid combination."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Open Public",
                "content": "test",
                "visibility": "public",
                "editability": "internal",
                "change_message": "valid combo",
            },
        )
        assert r.status_code == 302
        p = Page.objects.get(slug="open-public")
        assert p.editability == "internal"
        assert p.visibility == "public"

    def test_flp_editable_internal_visibility_is_valid(self, client, user):
        """FLP Staff editability + FLP Staff visibility is a valid combination."""
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Open Internal",
                "content": "test",
                "visibility": "internal",
                "editability": "internal",
                "change_message": "valid combo",
            },
        )
        assert r.status_code == 302
        p = Page.objects.get(slug="open-internal")
        assert p.editability == "internal"


# ── Page Links & Delete Protection ────────────────────────


class TestPageLinks:
    def test_saving_page_creates_links(self, user, page):
        """Saving a page with #slug references creates PageLink rows."""
        other = Page.objects.create(
            title="Target Page",
            slug="target-page",
            content="I am the target.",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        page.content = "Check out #target-page for details."
        page.save()
        assert PageLink.objects.filter(from_page=page, to_page=other).exists()

    def test_saving_page_removes_stale_links(self, user, page):
        """Editing a page to remove a #slug deletes the PageLink."""
        other = Page.objects.create(
            title="Target Page",
            slug="target-page",
            content="I am the target.",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        page.content = "Link to #target-page here."
        page.save()
        assert PageLink.objects.filter(from_page=page, to_page=other).exists()

        # Remove the link
        page.content = "No links anymore."
        page.save()
        assert not PageLink.objects.filter(
            from_page=page, to_page=other
        ).exists()

    def test_self_links_ignored(self, page):
        """A page linking to its own slug does not create a PageLink."""
        page.content = f"See #{page.slug} for more."
        page.save()
        assert not PageLink.objects.filter(from_page=page).exists()

    def test_update_fields_without_content_skips_link_update(self, user, page):
        """Saving with update_fields that excludes content skips
        link rebuild."""
        other = Page.objects.create(
            title="Target Page",
            slug="target-page",
            content="target",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        page.content = "Link to #target-page."
        page.save()
        assert PageLink.objects.filter(from_page=page, to_page=other).exists()

        # Save only visibility — links should remain unchanged
        page.visibility = "internal"
        page.save(update_fields=["visibility"])
        assert PageLink.objects.filter(from_page=page, to_page=other).exists()

    def test_slug_redirect_creates_link(self, user, page):
        """A #old-slug reference resolves via SlugRedirect."""
        other = Page.objects.create(
            title="Renamed Page",
            slug="new-slug",
            content="renamed",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        SlugRedirect.objects.create(old_slug="old-slug", page=other)
        page.content = "See #old-slug for details."
        page.save()
        assert PageLink.objects.filter(from_page=page, to_page=other).exists()

    def test_delete_blocked_by_incoming_links(self, client, user, page):
        """Cannot delete a page that has incoming links."""
        other = Page.objects.create(
            title="Linking Page",
            slug="linking-page",
            content=f"See #{page.slug} for info.",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        # Verify the link was created
        assert PageLink.objects.filter(from_page=other, to_page=page).exists()

        client.force_login(user)
        delete_url = reverse("page_delete", kwargs={"path": page.content_path})
        # GET shows the blocking message
        r = client.get(delete_url)
        assert r.status_code == 200
        assert b"cannot be deleted" in r.content
        assert b"Linking Page" in r.content

        # POST is also blocked
        r = client.post(delete_url)
        assert r.status_code == 302
        assert Page.objects.filter(pk=page.pk).exists()

    def test_delete_allowed_when_no_incoming_links(self, client, user, page):
        """A page with no incoming links can be deleted."""
        client.force_login(user)
        r = client.post(
            reverse("page_delete", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert not Page.objects.filter(pk=page.pk).exists()

    def test_delete_page_removes_outgoing_links(self, user, page):
        """Deleting a page cascades and removes its outgoing links."""
        Page.objects.create(
            title="Target",
            slug="target",
            content="target",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        page.content = "Link to #target."
        page.save()
        assert PageLink.objects.filter(from_page=page).exists()

        page.delete()
        assert not PageLink.objects.filter(from_page_id=page.pk).exists()


@pytest.mark.django_db
class TestPageBacklinks:
    def test_backlinks_page_shows_linking_pages(self, client, user, page):
        """The backlinks view lists pages that link to this page."""
        Page.objects.create(
            title="Linking Page",
            slug="linking-page",
            content=f"See #{page.slug} for info.",
            owner=user,
            created_by=user,
            updated_by=user,
        )
        backlinks_url = reverse(
            "page_backlinks", kwargs={"path": page.content_path}
        )
        r = client.get(backlinks_url)
        assert r.status_code == 200
        assert b"Linking Page" in r.content
        assert b"What links here" in r.content

    def test_backlinks_page_empty(self, client, user, page):
        """The backlinks view shows a message when no pages link here."""
        r = client.get(
            reverse(
                "page_backlinks",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 200
        assert b"No other pages link to this page" in r.content

    def test_backlinks_respects_view_permissions(self, client, user, page):
        """Backlinks hides pages the viewer can't access."""
        Page.objects.create(
            title="Secret Page",
            slug="secret-page",
            content=f"See #{page.slug} for info.",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="private",
        )
        # Anonymous user shouldn't see private linking page
        r = client.get(
            reverse(
                "page_backlinks",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 200
        assert b"Secret Page" not in r.content

    def test_backlinks_404_for_nonexistent_page(self, client):
        """Backlinks returns 404 for a page that doesn't exist."""
        r = client.get(
            reverse(
                "page_backlinks",
                kwargs={"path": "nonexistent-page"},
            )
        )
        assert r.status_code == 404


# ── Cleanup Command ───────────────────────────────────────


class TestCleanupCommand:
    def test_cleanup_deletes_expired_sessions(self, db):
        # Create an expired session
        Session.objects.create(
            session_key="expired123",
            session_data="data",
            expire_date=timezone.now() - timedelta(days=1),
        )
        call_command("cleanup")
        assert not Session.objects.filter(session_key="expired123").exists()

    def test_cleanup_clears_expired_magic_tokens(self, user):
        profile = user.profile
        profile.magic_link_token = "somehash"
        profile.magic_link_expires = timezone.now() - timedelta(hours=1)
        profile.save()

        call_command("cleanup")
        profile.refresh_from_db()
        assert profile.magic_link_token == ""
        assert profile.magic_link_expires is None

    def test_cleanup_deletes_old_orphaned_uploads(self, user):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("old.txt", b"data"),
            original_filename="old.txt",
        )
        # Backdate created_at to > 24 hours ago
        FileUpload.objects.filter(pk=upload.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        call_command("cleanup")
        assert not FileUpload.objects.filter(pk=upload.pk).exists()

    def test_cleanup_preserves_recent_orphaned_uploads(self, user):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("recent.txt", b"data"),
            original_filename="recent.txt",
        )
        call_command("cleanup")
        assert FileUpload.objects.filter(pk=upload.pk).exists()

    def test_cleanup_preserves_attached_uploads(self, user, page):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            page=page,
            file=SimpleUploadedFile("attached.txt", b"data"),
            original_filename="attached.txt",
        )
        FileUpload.objects.filter(pk=upload.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        call_command("cleanup")
        assert FileUpload.objects.filter(pk=upload.pk).exists()


# ── Edit Lock (Page) ─────────────────────────────────────


class TestPageEditLock:
    def test_edit_get_acquires_lock(self, client, user, page):
        client.force_login(user)
        client.get(reverse("page_edit", kwargs={"path": page.content_path}))
        assert EditLock.objects.filter(page=page, user=user).exists()

    def test_warning_shown_when_locked_by_other(
        self, client, user, other_user, page
    ):
        acquire_lock_for_page(page, other_user)
        client.force_login(user)
        r = client.get(
            reverse("page_edit", kwargs={"path": page.content_path})
        )
        assert r.status_code == 200
        assert b"Editing in Progress" in r.content
        assert b"Bob" in r.content

    def test_no_warning_when_locked_by_self(self, client, user, page):
        acquire_lock_for_page(page, user)
        client.force_login(user)
        r = client.get(
            reverse("page_edit", kwargs={"path": page.content_path})
        )
        assert r.status_code == 200
        assert b"Editing in Progress" not in r.content

    def test_override_takes_over_lock(self, client, user, other_user, page):
        acquire_lock_for_page(page, other_user)
        client.force_login(user)
        edit_url = reverse("page_edit", kwargs={"path": page.content_path})
        r = client.post(f"{edit_url}?override_lock=1")
        assert r.status_code == 302
        lock = EditLock.objects.get(page=page)
        assert lock.user == user

    def test_save_releases_lock(self, client, user, page):
        client.force_login(user)
        edit_url = reverse("page_edit", kwargs={"path": page.content_path})
        client.get(edit_url)
        assert EditLock.objects.filter(page=page).exists()
        client.post(
            edit_url,
            {
                "title": "Getting Started",
                "content": "Updated",
                "visibility": "public",
                "change_message": "Lock test",
            },
        )
        assert not EditLock.objects.filter(page=page).exists()

    def test_expired_lock_shows_no_warning(
        self, client, user, other_user, page
    ):
        acquire_lock_for_page(page, other_user)
        future = timezone.now() + EditLock.LOCK_DURATION * 2
        with time_machine.travel(future, tick=False):
            client.force_login(user)
            r = client.get(
                reverse(
                    "page_edit",
                    kwargs={"path": page.content_path},
                )
            )
            assert b"Editing in Progress" not in r.content


class TestCleanupCommandEditLocks:
    def test_cleanup_deletes_expired_edit_locks(self, user, page):
        acquire_lock_for_page(page, user)
        future = timezone.now() + EditLock.LOCK_DURATION * 2
        with time_machine.travel(future, tick=False):
            call_command("cleanup")
            assert not EditLock.objects.filter(page=page).exists()


# ── CSP Header Tests ──────────────────────────────────────


class TestCSPHeaders:
    """SECURITY: Content-Security-Policy headers must be present on all
    responses to prevent XSS, clickjacking, and other injection attacks."""

    def test_csp_header_on_page_detail(self, client, user, page):
        """Page detail responses include a CSP header."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert "Content-Security-Policy" in r

    def test_csp_header_on_root(self, client, user, root_directory):
        """Root directory response includes a CSP header."""
        client.force_login(user)
        r = client.get(reverse("root"))
        assert "Content-Security-Policy" in r

    def test_csp_blocks_frames(self, client, user, page):
        """CSP header includes frame-src 'none' to block embedding."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        csp = r["Content-Security-Policy"]
        assert "frame-src 'none'" in csp

    def test_csp_blocks_object(self, client, user, page):
        """CSP header includes object-src 'none' to block plugins."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        csp = r["Content-Security-Policy"]
        assert "object-src 'none'" in csp

    def test_csp_has_default_src(self, client, user, page):
        """CSP header includes a default-src directive."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        csp = r["Content-Security-Policy"]
        assert "default-src" in csp

    def test_csp_has_script_src(self, client, user, page):
        """CSP header includes a script-src directive."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        csp = r["Content-Security-Policy"]
        assert "script-src" in csp

    def test_csp_does_not_allow_unsafe_eval(self, client, user, page):
        """SECURITY: CSP must not include unsafe-eval now that Alpine CSP build is used."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        csp = r["Content-Security-Policy"]
        assert "'unsafe-eval'" not in csp


# ── Search Permission Filtering ──────────────────────────


class TestSearchPermissionFiltering:
    def test_anon_sees_only_public_pages(self, client, user, db):
        """Anonymous users should only see public pages."""
        Page.objects.create(
            title="Anon Public Page",
            content="anonvisibility content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        Page.objects.create(
            title="Anon Private Page",
            content="anonvisibility content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        r = client.get(f"{reverse('search')}?q=anonvisibility")
        content = r.content.decode()
        assert "Anon Public Page" in content
        assert "Anon Private Page" not in content

    def test_authenticated_sees_public_and_internal(self, client, user):
        """Authenticated users see public and internal pages."""
        pub = Page.objects.create(
            title="Public Search Test",
            content="searchterm alpha",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        internal = Page.objects.create(
            title="Internal Search Test",
            content="searchterm alpha",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INTERNAL,
        )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=searchterm")
        content = r.content.decode()
        assert pub.title in content
        assert internal.title in content

    def test_private_hidden_from_non_owner(
        self, client, other_user, private_page
    ):
        """Private pages should not be visible to non-owners."""
        client.force_login(other_user)
        r = client.get(f"{reverse('search')}?q=secret")
        assert private_page.title not in r.content.decode()

    def test_private_visible_to_owner(self, client, user, private_page):
        """Private pages should be visible to the owner."""
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=secret")
        assert private_page.title in r.content.decode()

    def test_page_in_private_dir_hidden(
        self, client, other_user, private_directory, user
    ):
        """Pages in private directories should be hidden from non-owners."""
        Page.objects.create(
            title="Hidden Dir Page",
            content="searchterm hidden",
            directory=private_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(other_user)
        r = client.get(f"{reverse('search')}?q=searchterm")
        assert "Hidden Dir Page" not in r.content.decode()

    def test_system_owner_sees_everything(
        self, client, owner_user, private_page
    ):
        """System owner should see all pages including private."""
        client.force_login(owner_user)
        r = client.get(f"{reverse('search')}?q=secret")
        assert private_page.title in r.content.decode()

    def test_pagination_returns_correct_count(self, client, user):
        """Regression: all matching public pages should be findable
        across paginated results (previously lost after position 25)."""
        for i in range(30):
            Page.objects.create(
                title=f"Bulk Page {i}",
                content="bulksearchterm content",
                owner=user,
                created_by=user,
                updated_by=user,
                visibility=Page.Visibility.PUBLIC,
            )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=bulksearchterm")
        assert "30 results" in r.content.decode()


# ── Search View ──────────────────────────────────────────


class TestSearchView:
    def test_empty_query_renders_form(self, client, user):
        """Empty query should render the search form without results."""
        client.force_login(user)
        r = client.get(reverse("search"))
        assert r.status_code == 200
        assert b"Search" in r.content

    def test_basic_search_returns_results(self, client, user, page):
        """Basic text query should return matching pages."""
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=Welcome")
        assert r.status_code == 200
        assert page.title in r.content.decode()

    def test_search_snippet_in_results(self, client, user, page):
        """Results should contain highlighted snippets with <mark> tags."""
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=Welcome")
        assert b"<mark>" in r.content

    def test_search_sort_edited_desc(self, client, user, page):
        """Sort=edited_desc should not error and should return results."""
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=Welcome&sort=edited_desc")
        assert r.status_code == 200
        assert page.title in r.content.decode()

    def test_search_pagination(self, client, user):
        """Pages beyond the first page should be accessible."""
        for i in range(25):
            Page.objects.create(
                title=f"Paginated Page {i}",
                content="paginationterm content",
                owner=user,
                created_by=user,
                updated_by=user,
                visibility=Page.Visibility.PUBLIC,
            )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=paginationterm&page=2")
        assert r.status_code == 200
        content = r.content.decode()
        assert "Paginated Page" in content

    def test_facets_show_directories(self, client, user, sub_directory):
        """Facet sidebar should show directories for matching pages."""
        Page.objects.create(
            title="Facet Test Page",
            content="facetterm content",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=facetterm")
        content = r.content.decode()
        assert "Engineering" in content

    def test_url_dir_filter_narrows_results(
        self, client, user, sub_directory, root_directory
    ):
        """URL dir= filter should narrow results to that directory."""
        Page.objects.create(
            title="Engineering Page",
            content="narrowterm content",
            directory=sub_directory,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        Page.objects.create(
            title="Other Page",
            content="narrowterm content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=narrowterm&in=engineering")
        content = r.content.decode()
        assert "Engineering Page" in content
        assert "Other Page" not in content

    def test_phrase_search(self, client, user):
        """Quoted phrase syntax should match exact phrases."""
        Page.objects.create(
            title="Phrase Match Page",
            content="the quick brown fox jumps over",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.get(f'{reverse("search")}?q="quick brown fox"')
        assert "Phrase Match Page" in r.content.decode()

    def test_exclude_search(self, client, user):
        """Minus prefix should exclude pages containing that term."""
        Page.objects.create(
            title="Keep This Page",
            content="excludetest content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        Page.objects.create(
            title="Exclude This Draft",
            content="excludetest draft content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PUBLIC,
        )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=excludetest -draft")
        content = r.content.decode()
        assert "Keep This Page" in content
        assert "Exclude This Draft" not in content

    def test_visibility_icon_shown(self, client, user):
        """Internal/private pages should show visibility icons."""
        Page.objects.create(
            title="Internal Icon Page",
            content="badgeterm content",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INTERNAL,
        )
        client.force_login(user)
        r = client.get(f"{reverse('search')}?q=badgeterm")
        # Building icon has title="FLP Staff"
        assert b'title="FLP Staff"' in r.content


class TestRawMarkdown:
    """Test the .md endpoint that returns raw markdown."""

    def test_returns_markdown_content(self, client, page):
        r = client.get(
            reverse(
                "page_raw_markdown",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 200
        assert r["Content-Type"] == "text/markdown"
        assert r.content.startswith(f"# {page.title}\n".encode())
        assert page.content.encode() in r.content

    def test_returns_markdown_for_page_in_directory(
        self, client, page_in_directory
    ):
        page = page_in_directory
        r = client.get(
            reverse(
                "page_raw_markdown",
                kwargs={"path": page.content_path},
            )
        )
        assert r.status_code == 200
        assert r["Content-Type"] == "text/markdown"

    def test_private_page_blocked_for_anonymous(self, client, private_page):
        r = client.get(
            reverse(
                "page_raw_markdown",
                kwargs={"path": private_page.content_path},
            )
        )
        assert r.status_code == 404

    def test_private_page_allowed_for_owner(self, client, user, private_page):
        client.force_login(user)
        r = client.get(
            reverse(
                "page_raw_markdown",
                kwargs={"path": private_page.content_path},
            )
        )
        assert r.status_code == 200
        assert f"# {private_page.title}".encode() in r.content
        assert private_page.content.encode() in r.content

    def test_nonexistent_page_returns_404(self, client, db):
        r = client.get(
            reverse(
                "page_raw_markdown",
                kwargs={"path": "no-such-page"},
            )
        )
        assert r.status_code == 404


# ── Upload ↔ Page Linking ─────────────────────────────────


class TestLinkUploadsToPage:
    """Verify that saving a page links referenced FileUploads."""

    def test_create_page_links_upload(self, client, user):
        """Uploading a file and saving a new page sets FileUpload.page."""
        client.force_login(user)
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("pic.png", b"img"),
            original_filename="pic.png",
            content_type="image/png",
        )
        assert upload.page is None

        r = client.post(
            reverse("page_create"),
            {
                "title": "Page With Image",
                "content": f"![pic](/files/{upload.pk}/pic.png)",
                "visibility": "public",
                "change_message": "Add image",
            },
        )
        assert r.status_code == 302
        upload.refresh_from_db()
        page = Page.objects.get(slug="page-with-image")
        assert upload.page == page

    def test_edit_page_links_new_upload(self, client, user, page):
        """Adding a file reference during edit links the upload."""
        client.force_login(user)
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("doc.pdf", b"pdf"),
            original_filename="doc.pdf",
            content_type="application/pdf",
        )
        edit_url = reverse("page_edit", kwargs={"path": page.content_path})
        r = client.post(
            edit_url,
            {
                "title": page.title,
                "content": f"See [doc](/files/{upload.pk}/doc.pdf)",
                "visibility": "public",
                "change_message": "Add doc",
            },
        )
        assert r.status_code == 302
        upload.refresh_from_db()
        assert upload.page == page

    def test_edit_page_unlinks_removed_upload(self, client, user, page):
        """Upload removed from content AND all revisions gets unlinked."""
        client.force_login(user)
        upload = FileUpload.objects.create(
            uploaded_by=user,
            page=page,
            file=SimpleUploadedFile("old.png", b"img"),
            original_filename="old.png",
        )
        # No revision references the upload, so removing from content
        # should unlink it.
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": page.title,
                "content": "No images here.",
                "visibility": "public",
                "change_message": "Remove image",
            },
        )
        assert r.status_code == 302
        upload.refresh_from_db()
        assert upload.page is None

    def test_edit_preserves_upload_referenced_by_revision(
        self, client, user, page
    ):
        """Upload stays linked if a past revision still references it."""
        client.force_login(user)
        upload = FileUpload.objects.create(
            uploaded_by=user,
            page=page,
            file=SimpleUploadedFile("rev-ref.png", b"img"),
            original_filename="rev-ref.png",
        )
        # Create a revision that references the upload
        page.content = f"![img](/files/{upload.pk}/rev-ref.png)"
        page.save()
        page.create_revision(user, "added image")

        # Edit page to remove the reference from current content
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": page.title,
                "content": "Image removed from current content.",
                "visibility": "public",
                "change_message": "Remove image",
            },
        )
        assert r.status_code == 302
        upload.refresh_from_db()
        # Upload should stay linked because a revision still references it
        assert upload.page == page

    def test_revert_links_uploads(self, client, user, page):
        """Reverting to a revision that references files links them."""
        client.force_login(user)
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("rev.png", b"img"),
            original_filename="rev.png",
            content_type="image/png",
        )
        edit_url = reverse("page_edit", kwargs={"path": page.content_path})
        # Edit page via view to add the file reference (links the upload)
        client.post(
            edit_url,
            {
                "title": page.title,
                "content": f"![img](/files/{upload.pk}/rev.png)",
                "visibility": "public",
                "change_message": "Add image",
            },
        )
        upload.refresh_from_db()
        assert upload.page == page
        page.refresh_from_db()
        rev_with_image = page.revisions.order_by("revision_number").last()

        # Edit page to remove the reference — upload stays linked
        # because the previous revision still references it.
        client.post(
            edit_url,
            {
                "title": page.title,
                "content": "No image.",
                "visibility": "public",
                "change_message": "Remove image",
            },
        )
        upload.refresh_from_db()
        assert upload.page == page

        # Revert to the revision that had the image
        r = client.post(
            reverse(
                "page_revert",
                kwargs={
                    "path": page.content_path,
                    "rev_num": rev_with_image.revision_number,
                },
            )
        )
        assert r.status_code == 302
        upload.refresh_from_db()
        assert upload.page == page

    def test_cannot_claim_another_users_upload(self, client, user, page):
        """Embedding another user's orphaned upload ID does not link it."""
        from django.contrib.auth.models import User

        other = User.objects.create_user("other", password="test")
        foreign_upload = FileUpload.objects.create(
            uploaded_by=other,
            file=SimpleUploadedFile("secret.png", b"secret"),
            original_filename="secret.png",
        )
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": page.title,
                "content": f"![stolen](/files/{foreign_upload.pk}/secret.png)",
                "visibility": "public",
                "change_message": "Try to steal",
            },
        )
        assert r.status_code == 302
        foreign_upload.refresh_from_db()
        # Upload must remain unlinked — not claimed by another user
        assert foreign_upload.page is None

    def test_cannot_claim_upload_linked_to_another_page(
        self, client, user, page
    ):
        """Referencing a file already linked to another page leaves it."""
        other_page = Page.objects.create(
            title="Other",
            content="x",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility="private",
        )
        upload = FileUpload.objects.create(
            uploaded_by=user,
            page=other_page,
            file=SimpleUploadedFile("attached.png", b"img"),
            original_filename="attached.png",
        )
        client.force_login(user)
        r = client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
            {
                "title": page.title,
                "content": f"![img](/files/{upload.pk}/attached.png)",
                "visibility": "public",
                "change_message": "Try to steal from other page",
            },
        )
        assert r.status_code == 302
        upload.refresh_from_db()
        # Upload must stay on its original page
        assert upload.page == other_page

    def test_cleanup_preserves_linked_upload(self, user, page):
        """Uploads linked via page save survive the orphan cleanup."""
        upload = FileUpload.objects.create(
            uploaded_by=user,
            page=page,
            file=SimpleUploadedFile("safe.png", b"img"),
            original_filename="safe.png",
        )
        FileUpload.objects.filter(pk=upload.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )
        call_command("cleanup")
        assert FileUpload.objects.filter(pk=upload.pk).exists()


# ── Search Content Command ────────────────────────────────


class TestSearchContentCommand:
    def test_broken_files_detects_missing_upload(self, page, capsys):
        """--broken-files reports file IDs not in FileUpload table."""
        page.content = "![gone](/files/99999/gone.png)"
        page.save()

        call_command("search_content", broken_files=True)
        captured = capsys.readouterr()
        assert "99999" in captured.out
        assert "broken" in captured.out.lower()

    def test_broken_files_passes_when_all_valid(self, user, page, capsys):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            page=page,
            file=SimpleUploadedFile("ok.png", b"img"),
            original_filename="ok.png",
        )
        page.content = f"![ok](/files/{upload.pk}/ok.png)"
        page.save()

        call_command("search_content", broken_files=True)
        captured = capsys.readouterr()
        assert "valid" in captured.out.lower()
        assert "broken" not in captured.out.lower()

    def test_pattern_search_finds_match(self, page, capsys):
        page.content = "The quick brown fox jumps over the lazy dog."
        page.save()

        call_command("search_content", "quick brown")
        captured = capsys.readouterr()
        assert page.title in captured.out

    def test_pattern_search_no_match(self, page, capsys):
        page.content = "Nothing special here."
        page.save()

        call_command("search_content", "xyzzyplugh")
        captured = capsys.readouterr()
        assert "0 page(s)" in captured.out


# ── Image optimization tests ──────────────────────────────────────


def _make_jpeg(width=200, height=200, color="red"):
    """Create a JPEG image with Pillow and return its bytes."""

    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    # Save unoptimized so there's room to compress
    img.save(buf, format="JPEG", quality=100)
    buf.seek(0)
    return buf.read()


def _make_png(width=200, height=200, color="blue"):
    """Create a PNG image with Pillow and return its bytes."""

    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _make_webp(width=200, height=200, color="green"):
    """Create a WebP image with Pillow and return its bytes."""

    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=100)
    buf.seek(0)
    return buf.read()


@pytest.mark.django_db
class TestImageOptimization:
    def test_optimize_jpeg(self, user):
        data = _make_jpeg()
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("photo.jpg", data),
            original_filename="photo.jpg",
            content_type="image/jpeg",
        )
        assert upload.optimization_gain is None

        count = optimize_images()

        assert count == 1
        upload.refresh_from_db()
        assert upload.optimization_gain is not None
        assert upload.optimization_gain != 0  # not an error

    def test_optimize_png(self, user):
        data = _make_png()
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("chart.png", data),
            original_filename="chart.png",
            content_type="image/png",
        )

        optimize_images()
        upload.refresh_from_db()
        assert upload.optimization_gain is not None

    def test_optimize_webp(self, user):
        data = _make_webp()
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("pic.webp", data),
            original_filename="pic.webp",
            content_type="image/webp",
        )

        optimize_images()
        upload.refresh_from_db()
        assert upload.optimization_gain is not None

    def test_skips_svg(self, user):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("icon.svg", b"<svg></svg>"),
            original_filename="icon.svg",
            content_type="image/svg+xml",
        )

        count = optimize_images()
        assert count == 0
        upload.refresh_from_db()
        assert upload.optimization_gain is None  # still pending

    def test_skips_gif(self, user):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("anim.gif", b"GIF89a"),
            original_filename="anim.gif",
            content_type="image/gif",
        )

        count = optimize_images()
        assert count == 0
        upload.refresh_from_db()
        assert upload.optimization_gain is None

    def test_skips_non_image(self, user):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("doc.pdf", b"%PDF-1.4"),
            original_filename="doc.pdf",
            content_type="application/pdf",
        )

        count = optimize_images()
        assert count == 0
        upload.refresh_from_db()
        assert upload.optimization_gain is None

    def test_idempotent(self, user):
        data = _make_jpeg()
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("done.jpg", data),
            original_filename="done.jpg",
            content_type="image/jpeg",
        )
        optimize_images()
        upload.refresh_from_db()
        first_gain = upload.optimization_gain

        # Running again should not reprocess
        count = optimize_images()
        assert count == 0
        upload.refresh_from_db()
        assert upload.optimization_gain == first_gain

    def test_corrupt_file_sets_zero(self, user):
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("bad.jpg", b"not-an-image"),
            original_filename="bad.jpg",
            content_type="image/jpeg",
        )

        count = optimize_images()
        assert count == 1
        upload.refresh_from_db()
        assert upload.optimization_gain == 0

    def test_batch_limit(self, user):
        for i in range(OPTIMIZE_BATCH_SIZE + 5):
            FileUpload.objects.create(
                uploaded_by=user,
                file=SimpleUploadedFile(f"img{i}.jpg", _make_jpeg()),
                original_filename=f"img{i}.jpg",
                content_type="image/jpeg",
            )

        count = optimize_images()
        assert count == OPTIMIZE_BATCH_SIZE

        # Second run picks up the remaining 5
        count2 = optimize_images()
        assert count2 == 5

    def test_preserves_storage_key(self, user):
        data = _make_jpeg()
        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("keep-key.jpg", data),
            original_filename="keep-key.jpg",
            content_type="image/jpeg",
        )
        original_name = upload.file.name

        optimize_images()
        upload.refresh_from_db()
        assert upload.file.name == original_name

    def test_already_optimized_not_replaced(self, user):
        """When optimization can't improve the file, original is kept."""

        # Create a tiny 1x1 JPEG — already minimal, hard to compress further
        img = PILImage.new("RGB", (1, 1), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        buf.seek(0)
        tiny_data = buf.read()

        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("tiny.jpg", tiny_data),
            original_filename="tiny.jpg",
            content_type="image/jpeg",
        )

        optimize_images()
        upload.refresh_from_db()

        # gain should be <= 0 (no improvement)
        assert upload.optimization_gain is not None
        assert upload.optimization_gain <= 0
        # File content should still be readable
        upload.file.seek(0)
        assert len(upload.file.read()) > 0

    def test_rgba_jpeg_conversion(self, user):
        """RGBA images saved as JPEG are converted to RGB."""

        img = PILImage.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        # Save as PNG first (JPEG can't store RGBA)
        img.save(buf, format="PNG")
        buf.seek(0)

        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("alpha.jpg", buf.read()),
            original_filename="alpha.jpg",
            content_type="image/jpeg",
        )

        # Should not crash
        count = optimize_images()
        assert count == 1
        upload.refresh_from_db()
        assert upload.optimization_gain is not None


# ── Directory-scoped slugs ──────────────────────────────


@pytest.mark.django_db
class TestDirectoryScopedSlugs:
    """Two pages may share a slug across different directories, and wiki-link
    resolution, URL resolution, and collision rewrites must all behave."""

    def _make_page(self, user, title, directory=None, content=""):
        p = Page.objects.create(
            title=title,
            content=content,
            directory=directory,
            owner=user,
            created_by=user,
            updated_by=user,
        )
        PageRevision.objects.create(
            page=p,
            title=p.title,
            content=p.content,
            change_message="seed",
            revision_number=1,
            created_by=user,
        )
        return p

    def test_two_pages_same_slug_different_dirs_coexist(
        self, user, sub_directory, nested_directory
    ):
        a = self._make_page(user, "Overview", directory=sub_directory)
        b = self._make_page(user, "Overview", directory=nested_directory)
        assert a.slug == "overview"
        assert b.slug == "overview"

    def test_url_resolves_each_page_at_qualified_path(
        self, client, user, sub_directory, nested_directory
    ):
        self._make_page(user, "Overview", directory=sub_directory)
        self._make_page(user, "Overview", directory=nested_directory)
        r = client.get(
            reverse("resolve_path", kwargs={"path": "engineering/overview"})
        )
        assert r.status_code == 200
        r = client.get(
            reverse(
                "resolve_path", kwargs={"path": "engineering/devops/overview"}
            )
        )
        assert r.status_code == 200

    def test_bare_path_404s_when_no_root_page(
        self, client, user, sub_directory
    ):
        """With dir-scoped slugs, /c/overview only resolves to a root page."""
        self._make_page(user, "Overview", directory=sub_directory)
        r = client.get(reverse("resolve_path", kwargs={"path": "overview"}))
        assert r.status_code == 404

    def test_qualified_wiki_link_resolves(
        self, user, sub_directory, nested_directory
    ):
        a = self._make_page(user, "Overview", directory=sub_directory)
        self._make_page(user, "Overview", directory=nested_directory)
        linker = self._make_page(
            user,
            "Linker",
            content=f"See #{a.content_path} for context.",
        )
        html = render_markdown(linker.content)
        assert a.get_absolute_url() in html

    def test_bare_wiki_link_resolves_to_oldest_match(
        self, user, sub_directory, nested_directory
    ):
        a = self._make_page(user, "Overview", directory=sub_directory)
        b = self._make_page(user, "Overview", directory=nested_directory)
        assert a.created_at < b.created_at
        html = render_markdown("See #overview for context.")
        assert a.get_absolute_url() in html
        assert b.get_absolute_url() not in html

    def test_collision_rewrite_qualifies_existing_links(
        self, user, sub_directory, nested_directory
    ):
        """Creating a page with a colliding slug rewrites existing bare
        references to the older page so they stay unambiguous."""
        a = self._make_page(user, "Overview", directory=sub_directory)
        linker = self._make_page(
            user,
            "Linker",
            content=(
                "Main: #overview\n\n"
                "Inline: [here](#overview) with fragment [sec](#overview#sec)\n\n"
                "Ref: [r]\n\n[r]: #overview\n"
            ),
        )
        # Baseline: PageLink points at A, content has bare links.
        assert PageLink.objects.filter(from_page=linker, to_page=a).exists()
        assert "#overview" in linker.content

        # Introduce a colliding page in a different directory.
        self._make_page(user, "Overview", directory=nested_directory)

        linker.refresh_from_db()
        expected = f"#{a.content_path}"
        assert "#overview\n" not in linker.content
        assert expected in linker.content
        # Fragment preserved
        assert f"{expected}#sec" in linker.content
        # PageLink to A still holds after rewrite
        assert PageLink.objects.filter(from_page=linker, to_page=a).exists()

    def test_collision_rewrite_leaves_code_blocks_alone(
        self, user, sub_directory, nested_directory
    ):
        a = self._make_page(user, "Overview", directory=sub_directory)
        linker = self._make_page(
            user,
            "Docs",
            content=(
                "Use `#overview` inline.\n\n"
                "```\nExample: #overview\n```\n\n"
                "Real link: #overview\n"
            ),
        )
        # Force PageLink setup before collision
        assert PageLink.objects.filter(from_page=linker, to_page=a).exists()

        self._make_page(user, "Overview", directory=nested_directory)

        linker.refresh_from_db()
        # Code-block contents untouched
        assert "Use `#overview`" in linker.content
        assert "Example: #overview" in linker.content
        # Real link qualified
        assert f"Real link: #{a.content_path}" in linker.content

    def test_slug_redirect_scoped_to_directory(
        self, client, user, sub_directory, nested_directory
    ):
        """A SlugRedirect only fires within its own (directory, slug) scope."""
        a = self._make_page(user, "Overview", directory=sub_directory)
        SlugRedirect.objects.create(
            directory=sub_directory, old_slug="old-name", page=a
        )
        # Within sub_directory, old-name redirects to a.
        r = client.get(
            reverse("resolve_path", kwargs={"path": "engineering/old-name"})
        )
        assert r.status_code == 302
        assert r.url == a.get_absolute_url()
        # From a different directory, the same old slug doesn't resolve.
        r = client.get(
            reverse(
                "resolve_path",
                kwargs={"path": "engineering/devops/old-name"},
            )
        )
        assert r.status_code == 404
