"""Tests for the pages app: CRUD, history, diff, search, wiki links."""

import json
from datetime import timedelta

import pytest
import time_machine
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from wiki.lib.edit_lock import acquire_lock_for_page
from wiki.lib.markdown import render_markdown, resolve_wiki_links
from wiki.lib.models import EditLock
from wiki.lib.permissions import can_edit_page
from wiki.pages.diff_utils import unified_diff
from wiki.pages.models import (
    FileUpload,
    Page,
    PageLink,
    PageRevision,
    PageViewTally,
    SlugRedirect,
)
from wiki.pages.tasks import sync_page_view_counts, update_search_vectors
from wiki.subscriptions.models import PageSubscription


@pytest.fixture
def client():
    return Client()


# ── Page CRUD ──────────────────────────────────────────────


class TestPageCreate:
    def test_create_requires_login(self, client, db):
        r = client.get("/c/new/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_create_page(self, client, user):
        client.force_login(user)
        r = client.post(
            "/c/new/",
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
            "/c/new/",
            {
                "title": "My Great Page",
                "content": "",
                "visibility": "public",
                "change_message": "Test",
            },
        )
        assert Page.objects.filter(slug="my-great-page").exists()

    def test_create_auto_subscribes_creator(self, client, user):
        from wiki.subscriptions.models import PageSubscription

        client.force_login(user)
        client.post(
            "/c/new/",
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
            "/c/engineering/new/",
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


class TestPageDetail:
    def test_public_page_visible_to_anon(self, client, page):
        r = client.get("/c/getting-started")
        assert r.status_code == 200
        assert b"Getting Started" in r.content

    def test_private_page_hidden_from_anon(self, client, private_page):
        r = client.get("/c/secret-notes")
        assert r.status_code == 404

    def test_private_page_visible_to_owner(self, client, user, private_page):
        client.force_login(user)
        r = client.get("/c/secret-notes")
        assert r.status_code == 200

    def test_private_page_hidden_from_other_user(
        self, client, other_user, private_page
    ):
        client.force_login(other_user)
        r = client.get("/c/secret-notes")
        assert r.status_code == 404

    def test_private_page_visible_to_system_owner(
        self, client, other_user, private_page
    ):
        from wiki.users.models import SystemConfig

        SystemConfig.objects.create(owner=other_user)
        client.force_login(other_user)
        r = client.get("/c/secret-notes")
        assert r.status_code == 200

    def test_records_page_view_tally(self, client, page):
        assert PageViewTally.objects.count() == 0
        client.get("/c/getting-started")
        assert PageViewTally.objects.count() == 1

    def test_breadcrumbs_on_page(self, client, page):
        r = client.get("/c/getting-started")
        assert b"Home" in r.content

    def test_breadcrumbs_in_directory(
        self, client, page_in_directory, sub_directory
    ):
        r = client.get(f"/c/{page_in_directory.slug}")
        assert b"Engineering" in r.content

    def test_breadcrumbs_hide_private_ancestor(
        self, client, other_user, user, root_directory
    ):
        """SECURITY: private ancestor directories must not appear in
        breadcrumbs for users who lack permission."""
        from wiki.directories.models import Directory

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
        r = client.get(f"/c/{p.slug}")
        assert r.status_code == 200
        assert b"Classified" not in r.content
        assert b"Public Child" in r.content

    def test_subscription_button_for_authenticated(self, client, user, page):
        client.force_login(user)
        r = client.get("/c/getting-started")
        assert b"Subscribe" in r.content

    def test_markdown_rendered(self, client, page):
        r = client.get("/c/getting-started")
        assert b"<h2" in r.content


class TestPageEdit:
    def test_edit_requires_login(self, client, page):
        r = client.get("/c/getting-started/edit/")
        assert r.status_code == 302

    def test_edit_page(self, client, user, page):
        client.force_login(user)
        r = client.post(
            "/c/getting-started/edit/",
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

    def test_edit_creates_slug_redirect(self, client, user, page):
        client.force_login(user)
        client.post(
            "/c/getting-started/edit/",
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
            "/c/getting-started/edit/",
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
        for url in ["/c/new/", "/c/getting-started/edit/"]:
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
        r = client.post("/c/getting-started/delete/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_owner_can_delete(self, client, user, page):
        client.force_login(user)
        r = client.post("/c/getting-started/delete/")
        assert r.status_code == 302
        assert not Page.objects.filter(slug="getting-started").exists()

    def test_non_owner_cannot_delete(self, client, other_user, page):
        client.force_login(other_user)
        r = client.post("/c/getting-started/delete/")
        assert r.status_code == 302
        assert Page.objects.filter(slug="getting-started").exists()

    def test_system_owner_can_delete_any(self, client, other_user, page):
        from wiki.users.models import SystemConfig

        SystemConfig.objects.create(owner=other_user)
        client.force_login(other_user)
        r = client.post("/c/getting-started/delete/")
        assert r.status_code == 302
        assert not Page.objects.filter(slug="getting-started").exists()


# ── History & Diff ─────────────────────────────────────────


class TestPageHistory:
    def test_history_page_loads(self, client, page):
        r = client.get("/c/getting-started/history/")
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
        r = client.get("/c/getting-started/history/")
        assert b"v1" in r.content
        assert b"v2" in r.content


class TestPageDiff:
    @pytest.fixture
    def two_revisions(self, user, page):
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
        r = client.get("/c/getting-started/diff/1/2/")
        assert r.status_code == 200

    def test_diff_shows_changes(self, client, two_revisions):
        r = client.get("/c/getting-started/diff/1/2/")
        # Word-level highlighting wraps changed segments in <span> tags,
        # so check for the words rather than the full contiguous phrase.
        assert b"Changed" in r.content
        assert b"content" in r.content


class TestPageRevert:
    @pytest.fixture
    def edited_page(self, client, user, page):
        client.force_login(user)
        client.post(
            "/c/getting-started/edit/",
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
        r = client.post("/c/getting-started/revert/1/")
        assert r.status_code == 302
        edited_page.refresh_from_db()
        assert edited_page.content == "## Welcome\n\nHello world."
        assert edited_page.revisions.count() == 3


# ── Slug Redirects & URL Resolution ───────────────────────


class TestSlugRedirect:
    def test_old_slug_redirects_to_new(self, client, page):
        SlugRedirect.objects.create(old_slug="old-name", page=page)
        r = client.get("/c/old-name")
        assert r.status_code == 302
        assert r.url == page.get_absolute_url()


class TestResolvePathView:
    def test_resolves_directory(self, client, sub_directory):
        r = client.get("/c/engineering")
        assert r.status_code == 200
        assert b"Engineering" in r.content

    def test_resolves_page(self, client, page):
        r = client.get("/c/getting-started")
        assert r.status_code == 200
        assert b"Getting Started" in r.content

    def test_unknown_path_404(self, client, db):
        r = client.get("/c/nonexistent-page")
        assert r.status_code == 404


# ── HTMX API Endpoints ────────────────────────────────────


class TestPreviewEndpoint:
    def test_preview_returns_rendered_html(self, client, user):
        client.force_login(user)
        r = client.post(
            "/api/preview/",
            {"content": "## Hello"},
        )
        assert r.status_code == 200
        assert b"<h2" in r.content

    def test_preview_works_without_login(self, client, db):
        r = client.post("/api/preview/", {"content": "test"})
        assert r.status_code == 200


class TestFileUpload:
    def test_upload_image(self, client, user):
        client.force_login(user)
        img = SimpleUploadedFile(
            "test.png", b"\x89PNG\r\n\x1a\n", content_type="image/png"
        )
        r = client.post("/api/upload/", {"file": img})
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "![test.png]" in data["markdown"]

    def test_upload_non_image(self, client, user):
        client.force_login(user)
        doc = SimpleUploadedFile(
            "doc.pdf", b"PDF content", content_type="application/pdf"
        )
        r = client.post("/api/upload/", {"file": doc})
        data = json.loads(r.content)
        assert "[doc.pdf]" in data["markdown"]
        assert "!" not in data["markdown"]

    def test_upload_no_file_returns_400(self, client, user):
        client.force_login(user)
        r = client.post("/api/upload/")
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
            r = client.post("/api/upload/", {"file": f})
            assert r.status_code == 400, f"{ext} should be blocked"
            assert b"not allowed" in r.content

    def test_safe_extension_allowed(self, client, user):
        """SECURITY: normal file types should still be accepted."""
        client.force_login(user)
        f = SimpleUploadedFile(
            "notes.txt", b"hello", content_type="text/plain"
        )
        r = client.post("/api/upload/", {"file": f})
        assert r.status_code == 200


class TestPageSearchAutocomplete:
    def test_search_returns_matches(self, client, user, page):
        client.force_login(user)
        r = client.get("/api/page-search/?q=getting")
        assert r.status_code == 200
        assert b"getting-started" in r.content

    def test_search_short_query_returns_empty(self, client, user):
        client.force_login(user)
        r = client.get("/api/page-search/?q=g")
        assert r.status_code == 200
        assert r.content == b""

    def test_search_excludes_current_page(self, client, user, page):
        client.force_login(user)
        r = client.get("/api/page-search/?q=getting&exclude=getting-started")
        assert r.status_code == 200
        assert b"getting-started" not in r.content

    def test_search_hides_private_pages(
        self, client, other_user, private_page
    ):
        """SECURITY: private pages must not appear in autocomplete for
        users without permission."""
        client.force_login(other_user)
        r = client.get("/api/page-search/?q=secret")
        assert r.status_code == 200
        assert b"secret-notes" not in r.content

    def test_search_shows_private_page_to_owner(
        self, client, user, private_page
    ):
        """The page owner should still see their own private pages."""
        client.force_login(user)
        r = client.get("/api/page-search/?q=secret")
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
        r = client.get("/api/page-search/?q=onerror")
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
        r = client.get(f"/files/{upload.id}/test.txt")
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
        r = client.get(f"/files/{upload.id}/test.txt")
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
        r = client.get(f"/files/{upload.id}/secret.txt")
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
        r = client.get(f"/files/{upload.id}/secret.txt")
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
        assert "[Getting Started](/c/getting-started)" in result

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
        from django.core.management import call_command

        call_command("seed_help_pages")
        from wiki.directories.models import Directory

        assert Directory.objects.filter(path="help").exists()

    def test_creates_help_pages(self, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        from wiki.directories.models import Directory

        help_dir = Directory.objects.get(path="help")
        assert Page.objects.filter(directory=help_dir).count() == 11

    def test_pages_are_public(self, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        from wiki.directories.models import Directory

        help_dir = Directory.objects.get(path="help")
        for p in Page.objects.filter(directory=help_dir):
            assert p.visibility == Page.Visibility.PUBLIC

    def test_pages_have_revisions(self, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        from wiki.directories.models import Directory

        help_dir = Directory.objects.get(path="help")
        for p in Page.objects.filter(directory=help_dir):
            assert p.revisions.count() >= 1

    def test_idempotent(self, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        call_command("seed_help_pages")
        from wiki.directories.models import Directory

        help_dir = Directory.objects.get(path="help")
        assert Page.objects.filter(directory=help_dir).count() == 11

    def test_help_pages_accessible_via_url(self, client, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        r = client.get("/c/help")
        assert r.status_code == 200
        assert b"Help" in r.content

    def test_help_page_detail_loads(self, client, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        r = client.get("/c/markdown-syntax")
        assert r.status_code == 200
        assert b"Markdown Syntax" in r.content

    def test_wiki_links_resolve_between_help_pages(self, owner_user):
        from django.core.management import call_command

        call_command("seed_help_pages")
        page = Page.objects.get(slug="getting-started-guide")
        # The content has #markdown-syntax links
        from wiki.lib.markdown import resolve_wiki_links

        resolved = resolve_wiki_links(page.content)
        assert "[Markdown Syntax]" in resolved


# ── Change Message Required ──────────────────────────────


class TestChangeMessageRequired:
    def test_edit_rejects_empty_change_message(self, client, user, page):
        client.force_login(user)
        r = client.post(
            "/c/getting-started/edit/",
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
            "/c/new/",
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
        r = client.get("/c/getting-started/move/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_move_page_to_directory(self, client, user, page, sub_directory):
        client.force_login(user)
        r = client.post(
            "/c/getting-started/move/",
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
            f"/c/{page_in_directory.slug}/move/",
            {"directory": ""},
        )
        assert r.status_code == 302
        page_in_directory.refresh_from_db()
        assert page_in_directory.directory is None

    def test_non_editor_cannot_move(self, client, other_user, page):
        client.force_login(other_user)
        r = client.get("/c/getting-started/move/")
        assert r.status_code == 302


# ── Subscriber Display ───────────────────────────────────


class TestSubscriberDisplay:
    def test_subscribers_visible_to_authenticated(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        client.force_login(user)
        r = client.get("/c/getting-started")
        assert b"Watching:" in r.content
        assert b"Alice" in r.content

    def test_subscribers_hidden_from_anon(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        r = client.get("/c/getting-started")
        assert b"Watching:" not in r.content


# ── @-Mentions ───────────────────────────────────────────


class TestMentions:
    def test_extract_mentions(self):
        from wiki.pages.views import _extract_mentions

        result = _extract_mentions("Hello @mike and @bob!")
        assert "mike" in result
        assert "bob" in result

    def test_extract_no_mentions(self):
        from wiki.pages.views import _extract_mentions

        assert _extract_mentions("No mentions here") == []

    def test_mentions_do_not_auto_subscribe(
        self, client, user, other_user, page
    ):
        client.force_login(user)
        client.post(
            "/c/getting-started/edit/",
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
            "/c/getting-started/edit/",
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
        from wiki.pages.models import PagePermission

        client.force_login(user)
        client.post(
            "/c/secret-notes/edit/",
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
        from wiki.pages.models import PagePermission

        client.force_login(user)
        client.post(
            "/c/secret-notes/edit/",
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
        for url in ["/c/new/", "/c/getting-started/edit/"]:
            content = client.get(url).content.decode()
            assert 'id="preview-btn"' not in content

    def test_directory_form_no_separate_preview_button(
        self, client, user, root_directory, sub_directory
    ):
        client.force_login(user)
        for url in ["/c/new-dir/", "/c/engineering/edit-dir/"]:
            content = client.get(url).content.decode()
            assert 'id="preview-btn"' not in content

    def test_preview_api_still_works(self, client, user):
        client.force_login(user)
        r = client.post("/api/preview/", {"content": "## Test"})
        assert r.status_code == 200
        assert b"<h2" in r.content


class TestMentionSnippet:
    def test_get_content_snippet(self):
        from wiki.subscriptions.tasks import _get_content_snippet

        content = "Line 1\nLine 2\nHey @bob check\nLine 4\nLine 5"
        snippet = _get_content_snippet(content, "bob")
        assert "@bob" in snippet
        assert "Line 1" in snippet  # 2 lines before
        assert "Line 5" in snippet  # 2 lines after

    def test_snippet_empty_when_no_match(self):
        from wiki.subscriptions.tasks import _get_content_snippet

        assert _get_content_snippet("No mention here", "bob") == ""

    def test_mention_email_includes_snippet(
        self, client, user, other_user, page
    ):
        from django.core import mail

        client.force_login(user)
        client.post(
            "/c/getting-started/edit/",
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
        r = client.get("/api/user-search/?q=bob")
        assert r.status_code == 200
        import json

        data = json.loads(r.content)
        assert len(data) == 1
        assert data[0]["username"] == "bob"

    def test_user_search_short_query(self, client, user):
        client.force_login(user)
        r = client.get("/api/user-search/?q=")
        data = __import__("json").loads(r.content)
        assert data == []

    def test_user_search_excludes_self(self, client, user):
        client.force_login(user)
        r = client.get("/api/user-search/?q=alice")
        data = json.loads(r.content)
        usernames = [u["username"] for u in data]
        assert "alice" not in usernames


class TestPagePermissions:
    def test_permissions_requires_login(self, client, page):
        r = client.get("/c/getting-started/permissions/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_permissions_page_loads(self, client, user, page):
        client.force_login(user)
        r = client.get("/c/getting-started/permissions/")
        assert r.status_code == 200
        assert b"Permissions" in r.content

    def test_add_user_permission(self, client, user, other_user, page):
        from wiki.pages.models import PagePermission

        client.force_login(user)
        r = client.post(
            "/c/getting-started/permissions/",
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
        from wiki.pages.models import PagePermission

        client.force_login(user)
        r = client.post(
            "/c/getting-started/permissions/",
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
        from wiki.pages.models import PagePermission

        perm = PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="edit",
        )
        client.force_login(user)
        r = client.post(
            "/c/getting-started/permissions/",
            {"remove": perm.pk},
        )
        assert r.status_code == 302
        assert not PagePermission.objects.filter(pk=perm.pk).exists()

    def test_non_editor_cannot_access(self, client, other_user, page):
        client.force_login(other_user)
        r = client.get("/c/getting-started/permissions/")
        assert r.status_code == 302

    def test_group_permission_grants_view_on_private_page(
        self, client, other_user, user, group
    ):
        """A user in a group with VIEW on a private page can see it."""
        from wiki.pages.models import PagePermission

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
        r = client.get("/c/group-test")
        assert r.status_code == 404

        # Grant group VIEW permission and add user to group
        PagePermission.objects.create(
            page=p, group=group, permission_type="view"
        )
        other_user.groups.add(group)
        # Clear cached group IDs
        if hasattr(other_user, "_group_ids_cache"):
            del other_user._group_ids_cache

        r = client.get("/c/group-test")
        assert r.status_code == 200

    def test_group_edit_permission_allows_editing(
        self, client, other_user, page, group
    ):
        """A user in a group with EDIT permission can edit the page."""
        from wiki.pages.models import PagePermission

        PagePermission.objects.create(
            page=page, group=group, permission_type="edit"
        )
        other_user.groups.add(group)

        client.force_login(other_user)
        r = client.post(
            "/c/getting-started/edit/",
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
        r = client.get("/c/getting-started")
        assert b"Creator:" in r.content
        assert b"Alice" in r.content

    def test_owner_shown_as_admin(self, client, other_user, user, page):
        """Owner appears as admin when another user views."""
        from wiki.pages.models import PagePermission

        # Add other_user as OWNER permission (admin)
        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="owner",
        )
        r = client.get("/c/getting-started")
        assert b"Admins:" in r.content
        assert b"Bob" in r.content

    def test_editor_permission_shown(self, client, other_user, page):
        from wiki.pages.models import PagePermission

        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="edit",
        )
        r = client.get("/c/getting-started")
        assert b"Editors:" in r.content
        assert b"Bob" in r.content

    def test_admin_not_duplicated_in_editors(self, client, other_user, page):
        """A user with OWNER perm should only appear as admin, not editor."""
        from wiki.pages.models import PagePermission

        PagePermission.objects.create(
            page=page,
            user=other_user,
            permission_type="owner",
        )
        r = client.get("/c/getting-started")
        content = r.content.decode()
        # Bob should be in Admins but not Editors
        assert "Admins:" in content
        # Only one Bob badge should appear (in admins)
        assert content.count("Bob") == 1


class TestCheckMentionPermissions:
    def test_public_page_no_issues(self, client, user, page):
        client.force_login(user)
        import json

        r = client.post(
            "/api/check-mention-perms/",
            json.dumps({"page_slug": "getting-started", "usernames": ["bob"]}),
            content_type="application/json",
        )
        data = json.loads(r.content)
        assert data["users_without_access"] == []

    def test_private_page_flags_user(
        self, client, user, other_user, private_page
    ):
        client.force_login(user)
        import json

        r = client.post(
            "/api/check-mention-perms/",
            json.dumps(
                {
                    "page_slug": "secret-notes",
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
        r = client.get(f"/c/{private_directory.path}/new/")
        content = r.content.decode()
        # The visibility dropdown should have private selected
        assert "selected" in content
        assert "private" in content

    def test_cannot_create_public_page_in_private_dir(
        self, client, user, private_directory
    ):
        client.force_login(user)
        r = client.post(
            f"/c/{private_directory.path}/new/",
            {
                "title": "Public In Private",
                "content": "test",
                "visibility": "public",
                "change_message": "test",
                "directory_path": private_directory.path,
            },
        )
        # Should stay on the form with an error
        assert r.status_code == 200
        assert b"cannot be more open than its directory" in r.content
        assert not Page.objects.filter(slug="public-in-private").exists()

    def test_can_create_private_page_in_private_dir(
        self, client, user, private_directory
    ):
        client.force_login(user)
        r = client.post(
            f"/c/{private_directory.path}/new/",
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

    def test_cannot_edit_to_public_in_private_dir(
        self, client, user, private_directory
    ):
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
            f"/c/{private_directory.path}/{page.slug}/edit/",
            {
                "title": "Secret Page",
                "content": "updated",
                "visibility": "public",
                "change_message": "try public",
                "directory_path": private_directory.path,
            },
        )
        assert r.status_code == 200
        assert b"cannot be more open than its directory" in r.content

    def test_cannot_move_public_page_to_private_dir(
        self, client, user, private_directory, page
    ):
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/move/",
            {"directory": private_directory.pk},
        )
        assert r.status_code == 200
        assert (
            b"Cannot move a page into a more restrictive directory"
            in r.content
        )


class TestCheckPagePermissions:
    """Part 5: Unified permissions endpoint with linked slugs."""

    def test_linked_private_page_flagged(
        self, client, user, page, private_page
    ):
        """A public page linking to a private page gets flagged."""
        client.force_login(user)
        import json

        r = client.post(
            "/api/check-page-perms/",
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
        import json

        r = client.post(
            "/api/check-page-perms/",
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
        import json

        r = client.post(
            "/api/check-page-perms/",
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
        import json

        r = client.post(
            "/api/check-page-perms/",
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
        import json

        r = client.post(
            "/api/check-mention-perms/",
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
        from django.contrib.auth.models import AnonymousUser

        page.editability = "internal"
        page.save(update_fields=["editability"])
        assert not can_edit_page(AnonymousUser(), page)

    def test_create_page_with_editability(self, client, user):
        """Creating a page with editability='internal' works."""
        client.force_login(user)
        r = client.post(
            "/c/new/",
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
            "/c/new/",
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

    def test_cannot_set_flp_editable_with_private_visibility(
        self, client, user
    ):
        """FLP Staff editability + Private should be rejected."""
        client.force_login(user)
        r = client.post(
            "/c/new/",
            {
                "title": "Bad Combo",
                "content": "test",
                "visibility": "private",
                "editability": "internal",
                "change_message": "test",
            },
        )
        assert r.status_code == 200
        assert b"FLP Staff" in r.content
        assert not Page.objects.filter(slug="bad-combo").exists()

    def test_cannot_edit_to_flp_editable_with_private(self, client, user):
        """Editing a private page to FLP Staff editability should be rejected."""
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
            f"/c/{page.slug}/edit/",
            {
                "title": "Private Edit Test",
                "content": "updated",
                "visibility": "private",
                "editability": "internal",
                "change_message": "try bad combo",
            },
        )
        assert r.status_code == 200
        assert b"FLP Staff" in r.content

    def test_form_includes_editability_field(self, client, user):
        """The page form includes the editability dropdown."""
        client.force_login(user)
        r = client.get("/c/new/")
        assert b"id_editability" in r.content

    def test_flp_editable_public_is_valid(self, client, user):
        """FLP Staff editability + Public is a valid combination."""
        client.force_login(user)
        r = client.post(
            "/c/new/",
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
            "/c/new/",
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
        # GET shows the blocking message
        r = client.get(f"/c/{page.slug}/delete/")
        assert r.status_code == 200
        assert b"cannot be deleted" in r.content
        assert b"Linking Page" in r.content

        # POST is also blocked
        r = client.post(f"/c/{page.slug}/delete/")
        assert r.status_code == 302
        assert Page.objects.filter(pk=page.pk).exists()

    def test_delete_allowed_when_no_incoming_links(self, client, user, page):
        """A page with no incoming links can be deleted."""
        client.force_login(user)
        r = client.post(f"/c/{page.slug}/delete/")
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


# ── Cleanup Command ───────────────────────────────────────


class TestCleanupCommand:
    def test_cleanup_deletes_expired_sessions(self, db):
        from django.contrib.sessions.models import Session
        from django.core.management import call_command

        # Create an expired session
        Session.objects.create(
            session_key="expired123",
            session_data="data",
            expire_date=timezone.now() - timedelta(days=1),
        )
        call_command("cleanup")
        assert not Session.objects.filter(session_key="expired123").exists()

    def test_cleanup_clears_expired_magic_tokens(self, user):
        from django.core.management import call_command

        profile = user.profile
        profile.magic_link_token = "somehash"
        profile.magic_link_expires = timezone.now() - timedelta(hours=1)
        profile.save()

        call_command("cleanup")
        profile.refresh_from_db()
        assert profile.magic_link_token == ""
        assert profile.magic_link_expires is None

    def test_cleanup_deletes_old_orphaned_uploads(self, user):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.management import call_command

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
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.management import call_command

        upload = FileUpload.objects.create(
            uploaded_by=user,
            file=SimpleUploadedFile("recent.txt", b"data"),
            original_filename="recent.txt",
        )
        call_command("cleanup")
        assert FileUpload.objects.filter(pk=upload.pk).exists()

    def test_cleanup_preserves_attached_uploads(self, user, page):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.management import call_command

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
        client.get("/c/getting-started/edit/")
        assert EditLock.objects.filter(page=page, user=user).exists()

    def test_warning_shown_when_locked_by_other(
        self, client, user, other_user, page
    ):
        acquire_lock_for_page(page, other_user)
        client.force_login(user)
        r = client.get("/c/getting-started/edit/")
        assert r.status_code == 200
        assert b"Editing in Progress" in r.content
        assert b"Bob" in r.content

    def test_no_warning_when_locked_by_self(self, client, user, page):
        acquire_lock_for_page(page, user)
        client.force_login(user)
        r = client.get("/c/getting-started/edit/")
        assert r.status_code == 200
        assert b"Editing in Progress" not in r.content

    def test_override_takes_over_lock(self, client, user, other_user, page):
        acquire_lock_for_page(page, other_user)
        client.force_login(user)
        r = client.post("/c/getting-started/edit/?override_lock=1")
        assert r.status_code == 302
        lock = EditLock.objects.get(page=page)
        assert lock.user == user

    def test_save_releases_lock(self, client, user, page):
        client.force_login(user)
        client.get("/c/getting-started/edit/")
        assert EditLock.objects.filter(page=page).exists()
        client.post(
            "/c/getting-started/edit/",
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
            r = client.get("/c/getting-started/edit/")
            assert b"Editing in Progress" not in r.content


class TestCleanupCommandEditLocks:
    def test_cleanup_deletes_expired_edit_locks(self, user, page):
        from django.core.management import call_command

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
        r = client.get(f"/c/{page.slug}/")
        assert "Content-Security-Policy" in r

    def test_csp_header_on_root(self, client, user, root_directory):
        """Root directory response includes a CSP header."""
        client.force_login(user)
        r = client.get("/c/")
        assert "Content-Security-Policy" in r

    def test_csp_blocks_frames(self, client, user, page):
        """CSP header includes frame-src 'none' to block embedding."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/")
        csp = r["Content-Security-Policy"]
        assert "frame-src 'none'" in csp

    def test_csp_blocks_object(self, client, user, page):
        """CSP header includes object-src 'none' to block plugins."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/")
        csp = r["Content-Security-Policy"]
        assert "object-src 'none'" in csp

    def test_csp_has_default_src(self, client, user, page):
        """CSP header includes a default-src directive."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/")
        csp = r["Content-Security-Policy"]
        assert "default-src" in csp

    def test_csp_has_script_src(self, client, user, page):
        """CSP header includes a script-src directive."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/")
        csp = r["Content-Security-Policy"]
        assert "script-src" in csp

    def test_csp_does_not_allow_unsafe_eval(self, client, user, page):
        """SECURITY: CSP must not include unsafe-eval now that Alpine CSP build is used."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/")
        csp = r["Content-Security-Policy"]
        assert "'unsafe-eval'" not in csp
