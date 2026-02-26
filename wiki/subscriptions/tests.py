"""Tests for subscriptions: toggle, notify, unsubscribe."""

import pytest
from django.core import mail
from django.core.signing import Signer
from django.test import Client

from wiki.subscriptions.models import PageSubscription
from wiki.subscriptions.tasks import notify_subscribers


@pytest.fixture
def client():
    return Client()


class TestToggleSubscription:
    def test_subscribe_to_page(self, client, user, page):
        client.force_login(user)
        r = client.post(f"/c/{page.slug}/subscribe/")
        assert r.status_code == 302
        assert PageSubscription.objects.filter(user=user, page=page).exists()

    def test_unsubscribe_from_page(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        client.force_login(user)
        r = client.post(f"/c/{page.slug}/subscribe/")
        assert r.status_code == 302
        assert not PageSubscription.objects.filter(
            user=user, page=page
        ).exists()

    def test_htmx_subscribe_returns_button(self, client, user, page):
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/subscribe/",
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 200
        assert b"Unsubscribe" in r.content

    def test_htmx_unsubscribe_returns_button(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        client.force_login(user)
        r = client.post(
            f"/c/{page.slug}/subscribe/",
            HTTP_HX_REQUEST="true",
        )
        assert b"Subscribe" in r.content

    def test_requires_login(self, client, page):
        r = client.post(f"/c/{page.slug}/subscribe/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_get_returns_404(self, client, user, page):
        client.force_login(user)
        r = client.get(f"/c/{page.slug}/subscribe/")
        assert r.status_code == 404


class TestNotifySubscribers:
    def test_notifies_other_subscribers(self, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        notify_subscribers(page.id, user.id, "Updated content")
        assert len(mail.outbox) == 1
        assert other_user.email in mail.outbox[0].to
        assert page.title in mail.outbox[0].subject

    def test_does_not_notify_editor(self, user, page):
        PageSubscription.objects.create(user=user, page=page)
        notify_subscribers(page.id, user.id, "Self edit")
        assert len(mail.outbox) == 0

    def test_email_contains_unsubscribe_link(self, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        notify_subscribers(page.id, user.id, "Change")
        assert "unsubscribe" in mail.outbox[0].body.lower()

    def test_email_contains_page_url(self, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        notify_subscribers(page.id, user.id, "Change")
        assert page.get_absolute_url() in mail.outbox[0].body

    def test_does_not_notify_user_without_view_permission(
        self, user, other_user, private_page
    ):
        PageSubscription.objects.create(user=other_user, page=private_page)
        notify_subscribers(private_page.id, user.id, "Secret change")
        assert len(mail.outbox) == 0


class TestUnsubscribeLanding:
    def test_valid_token_shows_confirm(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.get(f"/unsubscribe/{token}/")
        assert r.status_code == 200
        assert b"Unsubscribe" in r.content

    def test_valid_token_post_unsubscribes(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.post(f"/unsubscribe/{token}/")
        assert r.status_code == 302
        assert not PageSubscription.objects.filter(
            user=user, page=page
        ).exists()

    def test_invalid_token_redirects(self, client, db):
        r = client.get("/unsubscribe/bad-token/")
        assert r.status_code == 302


class TestRevertNotifiesSubscribers:
    """Integration: reverting a page sends notification emails."""

    def test_revert_sends_notification(self, client, user, other_user, page):
        # Create revision 2 by editing
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/edit/",
            {
                "title": page.title,
                "content": "Edited content",
                "visibility": "public",
                "change_message": "An edit",
            },
        )
        mail.outbox.clear()

        # Subscribe another user, then revert to revision 1
        PageSubscription.objects.create(user=other_user, page=page)
        client.post(f"/c/{page.slug}/revert/1/")
        assert len(mail.outbox) == 1
        assert "Reverted to version 1" in mail.outbox[0].body


class TestEditNotifiesSubscribers:
    """Integration: editing a page sends notification emails."""

    def test_edit_sends_notification(self, client, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        client.force_login(user)
        client.post(
            f"/c/{page.slug}/edit/",
            {
                "title": page.title,
                "content": "New content",
                "visibility": "public",
                "change_message": "Big update",
            },
        )
        assert len(mail.outbox) == 1
        assert "Big update" in mail.outbox[0].body
