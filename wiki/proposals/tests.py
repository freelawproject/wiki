"""Tests for the proposals app: feedback page, review, accept, deny."""

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from wiki.lib.ratelimiter import get_ratelimit_ident, get_viewer_ip
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


# ── Feedback Page ─────────────────────────────────────────


class TestFeedbackPage:
    def test_feedback_page_loads_for_viewer(self, client, other_user, page):
        """A user who can view but not edit sees the feedback form."""
        client.force_login(other_user)
        r = client.get(
            reverse("page_feedback", kwargs={"path": page.content_path})
        )
        assert r.status_code == 200
        assert b"Feedback" in r.content

    def test_feedback_accessible_to_editor(self, client, user, page):
        """An editor/owner can access the feedback page to propose
        changes (e.g. for review before editing directly)."""
        client.force_login(user)
        r = client.get(
            reverse("page_feedback", kwargs={"path": page.content_path})
        )
        assert r.status_code == 200

    def test_propose_form_prefilled(self, client, other_user, page):
        """The propose form is pre-filled with the current page content."""
        client.force_login(other_user)
        r = client.get(
            reverse("page_feedback", kwargs={"path": page.content_path})
        )
        content = r.content.decode()
        assert page.title in content
        assert page.content in content

    def test_submit_proposal(self, client, other_user, page):
        """A viewer can submit a proposal via the feedback page."""
        client.force_login(other_user)
        r = client.post(
            reverse("page_feedback", kwargs={"path": page.content_path}),
            {
                "submit_proposal": "1",
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
            reverse("page_feedback", kwargs={"path": page.content_path}),
            {
                "submit_proposal": "1",
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
            reverse("page_feedback", kwargs={"path": page.content_path}),
            {
                "submit_proposal": "1",
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
        r = client.get(
            reverse(
                "page_feedback", kwargs={"path": private_page.content_path}
            )
        )
        assert r.status_code == 404


# ── Proposal List ──────────────────────────────────────────


class TestProposalList:
    def test_list_requires_edit_permission(self, client, other_user, page):
        """Non-editors can't see the proposals list."""
        client.force_login(other_user)
        r = client.get(
            reverse("proposal_list", kwargs={"path": page.content_path})
        )
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
        r = client.get(
            reverse("proposal_list", kwargs={"path": page.content_path})
        )
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
        r = client.get(
            reverse("proposal_list", kwargs={"path": page.content_path})
        )
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
        r = client.get(
            reverse(
                "proposal_review",
                kwargs={"path": page.slug, "pk": proposal.pk},
            )
        )
        assert r.status_code == 200
        assert b"Diff" in r.content

    def test_review_renders_proposed_content_preview(
        self, client, user, other_user, page
    ):
        """The review page renders the proposed markdown so the reviewer can
        preview it, not just read the raw diff (issue #110)."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="## Proposed Heading\n\nBody text.",
            change_message="Minor fix",
        )
        client.force_login(user)
        r = client.get(
            reverse(
                "proposal_review",
                kwargs={"path": page.slug, "pk": proposal.pk},
            )
        )
        assert r.status_code == 200
        assert b"Preview" in r.content
        assert b"Proposed Heading" in r.content
        assert b"<h2" in r.content

    def test_review_requires_edit_permission(self, client, other_user, page):
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="whatever",
            change_message="fix",
        )
        client.force_login(other_user)
        r = client.get(
            reverse(
                "proposal_review",
                kwargs={"path": page.slug, "pk": proposal.pk},
            )
        )
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
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
        )
        assert r.status_code == 302
        page.refresh_from_db()
        assert page.title == "Getting Started v2"
        assert page.content == "Brand new content"
        proposal.refresh_from_db()
        assert proposal.status == "accepted"

    def test_accept_of_retitled_page_redirects_old_url(
        self, client, user, other_user, page
    ):
        """Accepting a proposal that changes the title regenerates the slug,
        so the page's old URL has to keep resolving."""
        old_url = page.get_absolute_url()
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title="Getting Started v2",
            proposed_content="Brand new content",
            change_message="Major rewrite",
        )
        client.force_login(user)
        client.post(
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
        )
        page.refresh_from_db()
        assert page.get_absolute_url() != old_url
        r = client.get(old_url)
        assert r.status_code == 302
        assert r.url == page.get_absolute_url()

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
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_accept",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_deny",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_deny",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
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
            reverse(
                "proposal_deny",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
            {"denial_reason": "Incorrect info"},
        )
        proposer_emails = [m for m in mail.outbox if other_user.email in m.to]
        assert len(proposer_emails) == 1
        assert "denied" in proposer_emails[0].subject

    def test_decision_email_quotes_the_original_proposal(
        self, client, user, other_user, page
    ):
        """A denial quotes the change message it's responding to."""
        proposal = ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="Update the citation format.",
        )
        client.force_login(user)
        client.post(
            reverse(
                "proposal_deny",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
            {"denial_reason": "Already correct."},
        )
        body = [m for m in mail.outbox if other_user.email in m.to][0].body
        assert "Your original proposal, sent" in body
        assert "> Update the citation format." in body

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
            reverse(
                "proposal_deny",
                kwargs={"path": page.slug, "pk": proposal.pk},
            ),
        )
        anon_emails = [m for m in mail.outbox if "anon@example.com" in m.to]
        assert len(anon_emails) == 1


# ── Page Detail Integration ────────────────────────────────


class TestPageDetailFeedbackButtons:
    def test_non_editor_sees_feedback_button(self, client, other_user, page):
        """A viewer who can't edit sees the Feedback button."""
        client.force_login(other_user)
        r = client.get(page.get_absolute_url())
        assert b"Feedback" in r.content

    def test_editor_sees_edit_and_propose(self, client, user, page):
        """The page owner sees both Edit and Propose Change."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        content = r.content.decode()
        assert ">Edit<" in content
        assert "Propose Change" in content

    def test_editor_sees_feedback_count(self, client, user, other_user, page):
        """The owner sees 'Feedback (1)' when pending proposals exist."""
        ChangeProposal.objects.create(
            page=page,
            proposed_by=other_user,
            proposed_title=page.title,
            proposed_content="content",
            change_message="fix",
        )
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert b"Feedback (1)" in r.content

    def test_no_feedback_badge_when_none_pending(self, client, user, page):
        """No feedback badge shown when there are none."""
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert b"Feedback (" not in r.content


# ── FLP Staff Editability + Feedback Interaction ─────────


class TestFLPEditableFeedback:
    def test_flp_editable_user_can_access_feedback(
        self, client, other_user, editable_page
    ):
        """A logged-in user on an FLP-editable page can access the
        feedback page to propose changes."""
        client.force_login(other_user)
        r = client.get(
            reverse(
                "page_feedback", kwargs={"path": editable_page.content_path}
            )
        )
        assert r.status_code == 200


def _viewer(ip_and_port):
    return {"HTTP_CLOUDFRONT_VIEWER_ADDRESS": ip_and_port}


class TestFeedbackRateLimit:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    @pytest.fixture
    def url(self, editable_page):
        return reverse(
            "page_feedback", kwargs={"path": editable_page.content_path}
        )

    @override_settings(RATELIMIT_ENABLE=True)
    def test_anonymous_proposals_rate_limited(self, client, url):
        data = {"submit_proposal": "1", "proposed_title": ""}
        for _ in range(5):
            assert client.post(url, data).status_code == 200
        assert client.post(url, data).status_code == 429

    @override_settings(RATELIMIT_ENABLE=True)
    def test_get_not_rate_limited(self, client, url):
        for _ in range(15):
            assert client.get(url).status_code == 200

    @override_settings(RATELIMIT_ENABLE=True)
    def test_counts_by_viewer_address_not_port_or_remote_addr(
        self, client, url
    ):
        """CloudFront's random port and shifting edge IPs must not matter."""
        for i in range(5):
            r = client.post(
                url,
                {"submit_proposal": "1"},
                REMOTE_ADDR=f"10.0.0.{i}",
                **_viewer(f"203.0.113.7:{50000 + i}"),
            )
            assert r.status_code == 200
        r = client.post(
            url,
            {"submit_proposal": "1"},
            REMOTE_ADDR="10.0.0.99",
            **_viewer("203.0.113.7:61000"),
        )
        assert r.status_code == 429

    @override_settings(RATELIMIT_ENABLE=True)
    def test_other_viewers_unaffected(self, client, url):
        for _ in range(6):
            client.post(
                url, {"submit_proposal": "1"}, **_viewer("203.0.113.7:1")
            )
        r = client.post(
            url, {"submit_proposal": "1"}, **_viewer("203.0.113.8:1")
        )
        assert r.status_code == 200


class TestViewerIdent:
    @pytest.mark.parametrize(
        "header,expected",
        [
            ("96.23.39.106:51396", "96.23.39.106"),
            ("2600:1f18::1234:51396", "2600:1f18::1234"),
            ("[2600:1f18::1234]:51396", "2600:1f18::1234"),
            ("::ffff:96.23.39.106:51396", "96.23.39.106"),
        ],
    )
    def test_get_viewer_ip(self, rf, header, expected):
        request = rf.get("/", **_viewer(header))
        assert get_viewer_ip(request) == expected

    @pytest.mark.parametrize("header", ["", "garbage:123"])
    def test_falls_back_to_remote_addr(self, rf, header):
        request = rf.get("/", REMOTE_ADDR="192.0.2.1", **_viewer(header))
        assert get_viewer_ip(request) == "192.0.2.1"

    def test_ipv6_widened_to_slash_64(self, rf):
        a = rf.get("/", **_viewer("2600:1f18:1:2:aaaa::1:1"))
        b = rf.get("/", **_viewer("2600:1f18:1:2:bbbb::2:2"))
        assert get_ratelimit_ident("", a) == get_ratelimit_ident("", b)
        assert get_ratelimit_ident("", a) == "2600:1f18:1:2::"


class TestGlobalWriteRateLimit:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    @override_settings(RATELIMIT_ENABLE=True)
    def test_posts_to_any_url_capped(self, client):
        # Middleware runs before routing, so even unrouted URLs count.
        for _ in range(10):
            assert client.post("/no-such-endpoint/").status_code == 404
        assert client.post("/no-such-endpoint/").status_code == 429

    @override_settings(RATELIMIT_ENABLE=True)
    def test_gets_not_capped(self, client):
        for _ in range(50):
            assert client.get("/no-such-endpoint/").status_code == 404

    @override_settings(RATELIMIT_ENABLE=True)
    def test_exempt_endpoints_not_counted(self, client):
        url = reverse("record_page_view")
        for _ in range(15):
            assert client.post(url).status_code != 429
