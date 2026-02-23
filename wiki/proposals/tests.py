"""Tests for the proposals app: propose, review, accept, deny."""

import pytest
from django.core import mail
from django.test import Client

from wiki.pages.models import Page, PageRevision
from wiki.proposals.models import ChangeProposal


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def editable_page(user):
    """A public, FLP-editable page owned by user."""
    p = Page.objects.create(
        title="Open Docs",
        slug="open-docs",
        content="## Docs\n\nOriginal content.",
        owner=user,
        created_by=user,
        updated_by=user,
        visibility=Page.Visibility.PUBLIC,
        editability=Page.Editability.INTERNAL,
    )
    PageRevision.objects.create(
        page=p,
        title=p.title,
        content=p.content,
        change_message="Initial creation",
        revision_number=1,
        created_by=user,
    )
    return p


# ── Propose Changes ────────────────────────────────────────


class TestProposeChanges:
    def test_propose_page_loads_for_viewer(self, client, other_user, page):
        """A user who can view but not edit sees the propose form."""
        client.force_login(other_user)
        r = client.get(f"/c/{page.slug}/propose/")
        assert r.status_code == 200
        assert b"Propose Changes" in r.content

    def test_propose_redirects_editor_to_edit(self, client, user, page):
        """A user who can edit is redirected to the edit page."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/propose/")
        assert r.status_code == 302
        assert "/edit/" in r.url

    def test_propose_form_prefilled(self, client, other_user, page):
        """The propose form is pre-filled with the current page content."""
        client.force_login(other_user)
        r = client.get(f"/c/{page.slug}/propose/")
        content = r.content.decode()
        assert page.title in content
        assert page.content in content

    def test_submit_proposal(self, client, other_user, page):
        """A viewer can submit a proposal."""
        client.force_login(other_user)
        r = client.post(
            f"/c/{page.slug}/propose/",
            {
                "proposed_title": "Getting Started v2",
                "proposed_content": "Updated content",
                "change_message": "Improved intro",
            },
        )
        assert r.status_code == 302
        proposal = ChangeProposal.objects.get(page=page)
        assert proposal.proposed_by == other_user
        assert proposal.proposed_title == "Getting Started v2"
        assert proposal.status == "pending"

    def test_submit_sends_owner_email(self, client, other_user, page):
        """Submitting a proposal emails the page owner."""
        client.force_login(other_user)
        client.post(
            f"/c/{page.slug}/propose/",
            {
                "proposed_title": page.title,
                "proposed_content": "Fix typo",
                "change_message": "Typo fix",
            },
        )
        assert len(mail.outbox) == 1
        assert page.owner.email in mail.outbox[0].to
        assert "Change proposed" in mail.outbox[0].subject

    def test_anon_can_propose_on_public_page(self, client, page):
        """An anonymous user can propose changes on a public page."""
        r = client.post(
            f"/c/{page.slug}/propose/",
            {
                "proposed_title": page.title,
                "proposed_content": "Anon edit",
                "change_message": "Anon fix",
                "proposer_email": "anon@example.com",
            },
        )
        assert r.status_code == 302
        proposal = ChangeProposal.objects.get(page=page)
        assert proposal.proposed_by is None
        assert proposal.proposer_email == "anon@example.com"

    def test_anon_cannot_propose_on_private_page(self, client, private_page):
        """An anonymous user gets 404 for a private page."""
        r = client.get(f"/c/{private_page.slug}/propose/")
        assert r.status_code == 404


# ── Proposal List ──────────────────────────────────────────


class TestProposalList:
    def test_list_requires_edit_permission(self, client, other_user, page):
        """Non-editors can't see the proposals list."""
        client.force_login(other_user)
        r = client.get(f"/c/{page.slug}/proposals/")
        assert r.status_code == 302  # redirect with error

    def test_owner_sees_proposal_list(self, client, user, page):
        """The page owner can see the proposals list."""
        ChangeProposal.objects.create(
            page=page,
            proposed_by=None,
            proposed_title=page.title,
            proposed_content="New stuff",
            change_message="Improvement",
        )
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/proposals/")
        assert r.status_code == 200
        assert b"Improvement" in r.content

    def test_list_separates_pending_and_reviewed(
        self, client, user, other_user, page
    ):
        """Pending and reviewed proposals are shown separately."""
        ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="Pending",
            change_message="Pending change",
        )
        ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="Accepted",
            change_message="Accepted change",
            status=ChangeProposal.Status.ACCEPTED,
            reviewed_by=user,
        )
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/proposals/")
        content = r.content.decode()
        assert "Pending change" in content
        assert "Accepted change" in content


# ── Proposal Review ────────────────────────────────────────


class TestProposalReview:
    def test_review_shows_diff(self, client, user, other_user, page):
        """The review page shows a diff between current and proposed."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="## Welcome\n\nUpdated world.",
            change_message="Minor fix",
        )
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/proposals/{proposal.pk}/")
        assert r.status_code == 200
        assert b"Diff" in r.content

    def test_review_requires_edit_permission(self, client, other_user, page):
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="whatever",
            change_message="fix",
        )
        client.force_login(other_user)
        r = client.get(f"/c/{page.slug}/proposals/{proposal.pk}/")
        assert r.status_code == 302


# ── Accept Proposal ────────────────────────────────────────


class TestProposalAccept:
    def test_accept_updates_page(self, client, user, other_user, page):
        """Accepting a proposal updates the page content."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title="Getting Started v2",
            proposed_content="Brand new content",
            change_message="Major rewrite",
        )
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/accept/",
        )
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.title == "Getting Started v2"
        assert page.content == "Brand new content"
        proposal.refresh_from_db()
        assert proposal.status == "accepted"

    def test_accept_creates_revision(self, client, user, other_user, page):
        """Accepting a proposal creates a new page revision."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="Revised",
            change_message="Revision test",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/accept/",
        )
        assert page.revisions.count() == 2
        latest = page.revisions.order_by("-revision_number").first()
        assert latest.revision_number == 2
        assert "Accepted proposal" in latest.change_message

    def test_accept_with_tweaks(self, client, user, other_user, page):
        """Reviewer can tweak content before accepting."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title="Original Proposed",
            proposed_content="Original proposed content",
            change_message="test",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/accept/",
            {
                "title": "Tweaked Title",
                "content": "Tweaked content",
            },
        )
        page.refresh_from_db()
        assert page.title == "Tweaked Title"
        assert page.content == "Tweaked content"

    def test_accept_notifies_proposer(self, client, user, other_user, page):
        """Accepting sends an email to the proposer."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/accept/",
        )
        # Should have at least the proposer notification
        proposer_emails = [m for m in mail.outbox if other_user.email in m.to]
        assert len(proposer_emails) >= 1
        assert "accepted" in proposer_emails[0].subject

    def test_accept_only_pending(self, client, user, other_user, page):
        """Cannot accept an already-reviewed proposal."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
            status=ChangeProposal.Status.DENIED,
        )
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/accept/",
        )
        assert r.status_code == 404

    def test_accept_requires_post(self, client, user, other_user, page):
        """GET is not allowed for accept."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        r = client.get(
            f"/c/{page.slug}/proposals/{proposal.pk}/accept/",
        )
        assert r.status_code == 405


# ── Deny Proposal ──────────────────────────────────────────


class TestProposalDeny:
    def test_deny_marks_denied(self, client, user, other_user, page):
        """Denying sets status to denied with reason."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/deny/",
            {"denial_reason": "Not appropriate"},
        )
        assert r.status_code == 302
        proposal.refresh_from_db()
        assert proposal.status == "denied"
        assert proposal.denial_reason == "Not appropriate"

    def test_deny_does_not_change_page(self, client, user, other_user, page):
        """Denying a proposal does not modify the page."""
        original_content = page.content
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title="Different",
            proposed_content="Different content",
            change_message="fix",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/deny/",
        )
        page.refresh_from_db()
        assert page.content == original_content

    def test_deny_notifies_proposer(self, client, user, other_user, page):
        """Denying sends a notification email to the proposer."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/deny/",
            {"denial_reason": "Incorrect info"},
        )
        proposer_emails = [m for m in mail.outbox if other_user.email in m.to]
        assert len(proposer_emails) == 1
        assert "denied" in proposer_emails[0].subject

    def test_deny_notifies_anon_proposer_email(self, client, user, page):
        """Denying notifies an anonymous proposer via their email."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=None,
            proposer_email="anon@example.com",
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/proposals/{proposal.pk}/deny/",
        )
        anon_emails = [m for m in mail.outbox if "anon@example.com" in m.to]
        assert len(anon_emails) == 1


# ── Page Detail Integration ────────────────────────────────


class TestPageDetailProposalButtons:
    def test_non_editor_sees_propose_button(self, client, other_user, page):
        """A viewer who can't edit sees the Propose Changes button."""
        client.force_login(other_user)
        r = client.get(f"/c/{page.slug}")
        assert b"Propose Changes" in r.content

    def test_editor_does_not_see_propose_button(self, client, user, page):
        """The page owner sees Edit, not Propose Changes."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Propose Changes" not in r.content
        assert b"Edit" in r.content

    def test_editor_sees_proposal_count(self, client, user, other_user, page):
        """The owner sees 'Proposals (1)' when pending proposals exist."""
        ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Proposals (1)" in r.content

    def test_no_proposal_badge_when_none_pending(self, client, user, page):
        """No proposals badge shown when there are none."""
        client.force_login(user)
        r = client.get(f"/c/{page.slug}")
        assert b"Proposals (" not in r.content


# ── FLP Staff Editability + Proposals Interaction ─────────


class TestFLPEditableRedirectsPropose:
    def test_flp_editable_user_redirected_to_edit(
        self, client, other_user, editable_page
    ):
        """A logged-in user on an FLP-editable page is redirected
        from propose to edit (since they can edit)."""
        client.force_login(other_user)
        r = client.get(f"/c/{editable_page.slug}/propose/")
        assert r.status_code == 302
        assert "/edit/" in r.url
