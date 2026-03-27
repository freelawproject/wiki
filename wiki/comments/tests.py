"""Tests for the comments app: submit, detail, reply, resolve, review queue."""

import pytest
from django.core import mail
from django.test import Client

from wiki.comments.models import PageComment
from wiki.proposals.models import ChangeProposal


@pytest.fixture
def client():
    return Client()


# ── Submit Comment (via Feedback Page) ────────────────────


class TestSubmitComment:
    def test_submit_comment(self, client, other_user, page):
        """A viewer can submit a comment via the feedback page."""
        client.force_login(other_user)
        r = client.post(
            f"/c/{page.slug}/feedback/",
            {
                "submit_comment": "1",
                "message": "This page needs updating.",
            },
        )
        assert r.status_code == 302
        comment = PageComment.objects.get(page=page)
        assert comment.author == other_user
        assert comment.message == "This page needs updating."
        assert comment.status == "pending"

    def test_submit_comment_sends_owner_email(self, client, other_user, page):
        """Submitting a comment emails the page owner."""
        client.force_login(other_user)
        client.post(
            f"/c/{page.slug}/feedback/",
            {
                "submit_comment": "1",
                "message": "Please fix the intro.",
            },
        )
        assert len(mail.outbox) == 1
        assert page.owner.email in mail.outbox[0].to
        assert "comment" in mail.outbox[0].subject.lower()

    def test_anon_can_comment_on_public_page(self, client, page):
        """An anonymous user can leave a comment with optional email."""
        r = client.post(
            f"/c/{page.slug}/feedback/",
            {
                "submit_comment": "1",
                "message": "Anon feedback here.",
                "author_email": "anon@example.com",
            },
        )
        assert r.status_code == 302
        comment = PageComment.objects.get(page=page)
        assert comment.author is None
        assert comment.author_email == "anon@example.com"

    def test_anon_cannot_comment_on_private_page(self, client, private_page):
        """An anonymous user gets 404 for a private page."""
        r = client.get(f"/c/{private_page.slug}/feedback/")
        assert r.status_code == 404

    def test_editor_can_submit_comment(self, client, user, page):
        """Editors/owners can leave feedback via the propose workflow."""
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/feedback/",
            {
                "submit_comment": "1",
                "message": "Owner leaving a comment.",
            },
        )
        assert r.status_code == 302


# ── Comment Detail ────────────────────────────────────────


class TestCommentDetail:
    def test_detail_requires_login(self, client, page):
        """Comment detail requires authentication."""
        comment = PageComment.objects.create(page=page, message="Test comment")
        r = client.get(f"/c/{page.slug}/comments/{comment.pk}/")
        assert r.status_code == 302  # redirect to login

    def test_editor_sees_comment_detail(self, client, user, page):
        """Editor can view a comment."""
        comment = PageComment.objects.create(page=page, message="Test comment")
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/comments/{comment.pk}/")
        assert r.status_code == 200
        assert b"Test comment" in r.content

    def test_non_editor_gets_404(self, client, other_user, page):
        """Non-editors cannot view comment details."""
        comment = PageComment.objects.create(page=page, message="Test comment")
        client.force_login(other_user)
        r = client.get(f"/c/{page.slug}/comments/{comment.pk}/")
        assert r.status_code == 404

    def test_editor_sees_reply_form_on_pending(self, client, user, page):
        """Editor sees reply form for pending comments."""
        comment = PageComment.objects.create(page=page, message="Need help")
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/comments/{comment.pk}/")
        assert b"Send Reply" in r.content

    def test_no_reply_form_on_resolved(self, client, user, page):
        """No reply form shown for resolved comments."""
        comment = PageComment.objects.create(
            page=page,
            message="Done",
            status=PageComment.Status.RESOLVED,
        )
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/comments/{comment.pk}/")
        assert b"Send Reply" not in r.content


# ── Comment Reply ─────────────────────────────────────────


class TestCommentReply:
    def test_reply_saves_and_notifies(self, client, user, other_user, page):
        """Replying saves reply text and sends email to commenter."""
        comment = PageComment.objects.create(
            page=page,
            author=other_user,
            message="Please update.",
        )
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/comments/{comment.pk}/reply/",
            {"reply": "Done, thanks!"},
        )
        assert r.status_code == 302
        comment.refresh_from_db()
        assert comment.reply == "Done, thanks!"
        assert comment.replied_by == user
        assert comment.replied_at is not None
        # Check email notification
        reply_emails = [m for m in mail.outbox if other_user.email in m.to]
        assert len(reply_emails) == 1
        assert "Reply" in reply_emails[0].subject

    def test_reply_notifies_anon_email(self, client, user, page):
        """Replying notifies anonymous commenter via their email."""
        comment = PageComment.objects.create(
            page=page,
            author=None,
            author_email="anon@example.com",
            message="Anon comment",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/comments/{comment.pk}/reply/",
            {"reply": "Thanks for the feedback."},
        )
        anon_emails = [m for m in mail.outbox if "anon@example.com" in m.to]
        assert len(anon_emails) == 1

    def test_reply_requires_edit_permission(self, client, other_user, page):
        """Non-editors cannot reply to comments."""
        comment = PageComment.objects.create(page=page, message="Test")
        client.force_login(other_user)
        r = client.post(
            f"/c/{page.slug}/comments/{comment.pk}/reply/",
            {"reply": "Should fail"},
        )
        assert r.status_code == 404

    def test_reply_only_pending(self, client, user, page):
        """Cannot reply to a resolved comment."""
        comment = PageComment.objects.create(
            page=page,
            message="Old",
            status=PageComment.Status.RESOLVED,
        )
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/comments/{comment.pk}/reply/",
            {"reply": "Too late"},
        )
        assert r.status_code == 404


# ── Comment Resolve ───────────────────────────────────────


class TestCommentResolve:
    def test_resolve_marks_resolved(self, client, user, page):
        """Resolving sets status to resolved."""
        comment = PageComment.objects.create(page=page, message="Fix needed")
        client.force_login(user)
        r = client.post(f"/c/{page.slug}/comments/{comment.pk}/resolve/")
        assert r.status_code == 302
        comment.refresh_from_db()
        assert comment.status == "resolved"
        assert comment.resolved_by == user
        assert comment.resolved_at is not None

    def test_resolve_requires_edit_permission(self, client, other_user, page):
        """Non-editors cannot resolve comments."""
        comment = PageComment.objects.create(page=page, message="Test")
        client.force_login(other_user)
        r = client.post(f"/c/{page.slug}/comments/{comment.pk}/resolve/")
        assert r.status_code == 404

    def test_already_resolved_returns_404(self, client, user, page):
        """Cannot resolve an already-resolved comment."""
        comment = PageComment.objects.create(
            page=page,
            message="Done",
            status=PageComment.Status.RESOLVED,
        )
        client.force_login(user)
        r = client.post(f"/c/{page.slug}/comments/{comment.pk}/resolve/")
        assert r.status_code == 404


# ── Review Queue ──────────────────────────────────────────


class TestReviewQueue:
    def test_requires_login(self, client):
        """Review queue requires authentication."""
        r = client.get("/u/review/")
        assert r.status_code == 302

    def test_shows_pending_proposals(self, client, user, other_user, page):
        """Review queue shows pending proposals for owned pages."""
        ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="Fix typo",
        )
        client.force_login(user)
        r = client.get("/u/review/")
        assert r.status_code == 200
        assert b"Fix typo" in r.content

    def test_shows_pending_comments(self, client, user, page):
        """Review queue shows pending comments for owned pages."""
        PageComment.objects.create(
            page=page,
            message="Please update this section.",
        )
        client.force_login(user)
        r = client.get("/u/review/")
        assert r.status_code == 200
        assert b"Please update this section" in r.content

    def test_excludes_non_editable_pages(self, client, other_user, page):
        """Review queue excludes pages the user cannot edit."""
        PageComment.objects.create(
            page=page,
            message="Should not see this.",
        )
        client.force_login(other_user)
        r = client.get("/u/review/")
        assert r.status_code == 200
        assert b"Should not see this" not in r.content

    def test_empty_state(self, client, user, page):
        """Review queue shows empty state when no pending items."""
        client.force_login(user)
        r = client.get("/u/review/")
        assert r.status_code == 200
        assert b"No pending items" in r.content

    def test_new_owner_sees_existing_feedback(
        self, client, user, other_user, page
    ):
        """When page ownership changes, the new owner sees existing
        pending feedback in their review queue."""
        # Create feedback while user is owner
        PageComment.objects.create(page=page, message="Old comment")
        # Transfer ownership
        page.owner = other_user
        page.save()

        client.force_login(other_user)
        r = client.get("/u/review/")
        assert b"Old comment" in r.content

        # Original owner no longer sees it
        client.force_login(user)
        r = client.get("/u/review/")
        assert b"Old comment" not in r.content


# ── Navbar Badge ──────────────────────────────────────────


class TestNavbarBadge:
    def test_review_link_appears_with_pending(
        self, client, user, other_user, page
    ):
        """Review icon with badge appears when pending items exist."""
        PageComment.objects.create(page=page, message="Need fix")
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Review queue" in r.content
        assert b"bg-red-500" in r.content

    def test_review_link_hidden_when_none(self, client, user, page):
        """Review icon is hidden when no pending items."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Review queue" not in r.content


# ── Page Detail Comment Count ─────────────────────────────


class TestPageDetailCommentCount:
    def test_comment_count_in_feedback_badge(self, client, user, page):
        """Editor sees comment count included in feedback badge."""
        PageComment.objects.create(page=page, message="Comment 1")
        PageComment.objects.create(page=page, message="Comment 2")
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Feedback (2)" in r.content

    def test_combined_count(self, client, user, other_user, page):
        """Feedback badge shows combined proposal + comment count."""
        PageComment.objects.create(page=page, message="Comment")
        ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Feedback (2)" in r.content
