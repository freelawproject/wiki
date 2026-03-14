"""Tests for subscriptions: toggle, notify, unsubscribe."""

import pytest
from django.core import mail
from django.core.signing import Signer
from django.test import Client

from wiki.subscriptions.models import (
    DirectorySubscription,
    PageSubscription,
    SubscriptionExclusion,
)
from wiki.subscriptions.tasks import notify_subscribers
from wiki.subscriptions.utils import (
    get_effective_watchers_for_page,
    get_subscriber_info_for_page,
    is_effectively_subscribed_to_directory,
    is_effectively_subscribed_to_page,
)


@pytest.fixture
def client():
    return Client()


# ── Model tests ──────────────────────────────────────────────────


class TestDirectorySubscriptionModel:
    def test_create(self, user, sub_directory):
        ds = DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        assert ds.pk is not None
        assert str(ds) == f"{user} → {sub_directory}"

    def test_unique_together(self, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        with pytest.raises(Exception):
            DirectorySubscription.objects.create(
                user=user, directory=sub_directory
            )

    def test_cascade_delete_directory(self, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        sub_directory.delete()
        assert not DirectorySubscription.objects.filter(user=user).exists()


class TestSubscriptionExclusionModel:
    def test_page_exclusion(self, user, page):
        ex = SubscriptionExclusion.objects.create(user=user, page=page)
        assert ex.pk is not None

    def test_directory_exclusion(self, user, sub_directory):
        ex = SubscriptionExclusion.objects.create(
            user=user, directory=sub_directory
        )
        assert ex.pk is not None

    def test_cannot_have_both(self, user, page, sub_directory):
        with pytest.raises(Exception):
            SubscriptionExclusion.objects.create(
                user=user, page=page, directory=sub_directory
            )

    def test_cannot_have_neither(self, user, db):
        with pytest.raises(Exception):
            SubscriptionExclusion.objects.create(user=user)

    def test_unique_per_user_page(self, user, page):
        SubscriptionExclusion.objects.create(user=user, page=page)
        with pytest.raises(Exception):
            SubscriptionExclusion.objects.create(user=user, page=page)


# ── Utility function tests ───────────────────────────────────────


class TestGetSubscriberInfoForPage:
    def test_page_sub_only(self, user, page):
        PageSubscription.objects.create(user=user, page=page)
        page_subs, dir_subs = get_subscriber_info_for_page(page)
        assert user.id in page_subs
        assert not dir_subs

    def test_dir_sub(self, user, sub_directory, page_in_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        page_subs, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert not page_subs
        assert user.id in dir_subs
        assert dir_subs[user.id] == sub_directory

    def test_root_dir_sub(
        self, user, root_directory, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        _, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id in dir_subs

    def test_page_exclusion_blocks(
        self, user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        SubscriptionExclusion.objects.create(user=user, page=page_in_directory)
        _, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id not in dir_subs

    def test_dir_exclusion_blocks(
        self, user, root_directory, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=user, directory=sub_directory
        )
        _, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id not in dir_subs

    def test_closer_sub_overrides_parent_exclusion(
        self,
        user,
        root_directory,
        sub_directory,
        nested_directory,
        page_in_nested_directory,
    ):
        """User subscribes to root, excludes engineering, subscribes to devops.
        Should still get notifications for pages in devops."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=user, directory=sub_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=nested_directory
        )
        _, dir_subs = get_subscriber_info_for_page(page_in_nested_directory)
        assert user.id in dir_subs
        assert dir_subs[user.id] == nested_directory

    def test_both_page_and_dir_sub(
        self, user, sub_directory, page_in_directory
    ):
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        page_subs, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id in page_subs
        assert user.id in dir_subs

    def test_no_subs(self, page):
        page_subs, dir_subs = get_subscriber_info_for_page(page)
        assert not page_subs
        assert not dir_subs

    def test_page_without_directory(self, user, root_directory, page):
        """Pages without a directory are treated as root."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        _, dir_subs = get_subscriber_info_for_page(page)
        assert user.id in dir_subs


class TestIsEffectivelySubscribedToPage:
    def test_direct_sub(self, user, page):
        PageSubscription.objects.create(user=user, page=page)
        assert is_effectively_subscribed_to_page(user, page)

    def test_dir_sub(self, user, sub_directory, page_in_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        assert is_effectively_subscribed_to_page(user, page_in_directory)

    def test_excluded(self, user, sub_directory, page_in_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        SubscriptionExclusion.objects.create(user=user, page=page_in_directory)
        assert not is_effectively_subscribed_to_page(user, page_in_directory)

    def test_not_subscribed(self, user, page):
        assert not is_effectively_subscribed_to_page(user, page)

    def test_dir_exclusion_blocks(
        self, user, root_directory, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=user, directory=sub_directory
        )
        assert not is_effectively_subscribed_to_page(user, page_in_directory)


class TestIsEffectivelySubscribedToDirectory:
    def test_direct(self, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        assert is_effectively_subscribed_to_directory(user, sub_directory)

    def test_inherited(self, user, root_directory, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        assert is_effectively_subscribed_to_directory(user, sub_directory)

    def test_not_subscribed(self, user, sub_directory):
        assert not is_effectively_subscribed_to_directory(user, sub_directory)

    def test_excluded(self, user, root_directory, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=user, directory=sub_directory
        )
        assert not is_effectively_subscribed_to_directory(user, sub_directory)


class TestGetEffectiveWatchers:
    def test_combined(
        self, user, other_user, sub_directory, page_in_directory
    ):
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        watchers = get_effective_watchers_for_page(page_in_directory)
        watcher_ids = {w.id for w in watchers}
        assert user.id in watcher_ids
        assert other_user.id in watcher_ids

    def test_empty(self, page):
        watchers = get_effective_watchers_for_page(page)
        assert watchers.count() == 0


# ── User journey scenarios ───────────────────────────────────────


class TestUserJourneyScenarios:
    def test_page_sub_then_dir_sub_then_dir_unsub_preserves_page_sub(
        self, user, sub_directory, page_in_directory
    ):
        """Scenario 1: Subscribe to page → subscribe to parent dir →
        unsub from dir → still subscribed to page."""
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        # Unsubscribe from directory
        DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).delete()
        # Page subscription should still exist
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory
        ).exists()
        assert is_effectively_subscribed_to_page(user, page_in_directory)

    def test_dir_sub_then_exclude_page(
        self, user, sub_directory, page_in_directory
    ):
        """Scenario 2: Subscribe to dir, unsubscribe from sub-page →
        no notifications for that page."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        SubscriptionExclusion.objects.create(user=user, page=page_in_directory)
        assert not is_effectively_subscribed_to_page(user, page_in_directory)

    def test_dir_sub_then_exclude_subdir(
        self,
        user,
        root_directory,
        sub_directory,
        nested_directory,
        page_in_nested_directory,
    ):
        """Scenario 3: Subscribe to root, exclude engineering/devops →
        no notifications for pages in devops."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=user, directory=nested_directory
        )
        assert not is_effectively_subscribed_to_page(
            user, page_in_nested_directory
        )


# ── View tests ───────────────────────────────────────────────────


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

    def test_unsub_page_creates_exclusion_when_dir_subscribed(
        self, client, user, sub_directory, page_in_directory
    ):
        """Unsubscribing from a page when subscribed via directory
        should create an exclusion."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/{page_in_directory.slug}/subscribe/"
        )
        assert r.status_code == 302
        assert SubscriptionExclusion.objects.filter(
            user=user, page=page_in_directory
        ).exists()

    def test_subscribe_removes_exclusion(
        self, client, user, sub_directory, page_in_directory
    ):
        """Subscribing to a page should remove any exclusion."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        SubscriptionExclusion.objects.create(user=user, page=page_in_directory)
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/{page_in_directory.slug}/subscribe/"
        )
        assert r.status_code == 302
        assert not SubscriptionExclusion.objects.filter(
            user=user, page=page_in_directory
        ).exists()
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory
        ).exists()

    def test_unsub_both_direct_and_dir(
        self, client, user, sub_directory, page_in_directory
    ):
        """If user has both direct and dir sub, unsubscribe removes direct
        and creates exclusion."""
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/{page_in_directory.slug}/subscribe/"
        )
        assert r.status_code == 302
        assert not PageSubscription.objects.filter(
            user=user, page=page_in_directory
        ).exists()
        assert SubscriptionExclusion.objects.filter(
            user=user, page=page_in_directory
        ).exists()


class TestToggleDirectorySubscription:
    def test_subscribe_to_directory(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/subscribe-dir/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).exists()

    def test_unsubscribe_from_directory(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/subscribe-dir/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert not DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).exists()

    def test_subscribe_root(self, client, user, root_directory):
        client.force_login(user)
        r = client.post(
            "/c/subscribe-dir/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert DirectorySubscription.objects.filter(
            user=user, directory=root_directory
        ).exists()

    def test_requires_login(self, client, sub_directory):
        r = client.post(f"/c/{sub_directory.path}/subscribe-dir/")
        assert r.status_code == 302
        assert "/u/login/" in r.url

    def test_get_returns_404(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get(f"/c/{sub_directory.path}/subscribe-dir/")
        assert r.status_code == 404

    def test_unsub_creates_exclusion_when_parent_subscribed(
        self, client, user, root_directory, sub_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/subscribe-dir/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert not DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).exists()
        # Should create exclusion since parent sub still covers it
        assert SubscriptionExclusion.objects.filter(
            user=user, directory=sub_directory
        ).exists()

    def test_subscribe_removes_exclusion(
        self, client, user, root_directory, sub_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            f"/c/{sub_directory.path}/subscribe-dir/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert not SubscriptionExclusion.objects.filter(
            user=user, directory=sub_directory
        ).exists()
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).exists()

    def test_non_ajax_redirects(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(f"/c/{sub_directory.path}/subscribe-dir/")
        assert r.status_code == 302

    def test_non_ajax_unsub_redirects(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(f"/c/{sub_directory.path}/subscribe-dir/")
        assert r.status_code == 302


# ── Notification tests ───────────────────────────────────────────


class TestNotifyWithDirectorySubscriptions:
    def test_dir_subscriber_gets_notified(
        self, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Updated")
        assert len(mail.outbox) == 1
        assert other_user.email in mail.outbox[0].to

    def test_dir_subscriber_email_mentions_directory(
        self, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Updated")
        body = mail.outbox[0].body
        assert sub_directory.title in body
        assert "subscribed to" in body.lower()

    def test_dir_subscriber_email_has_two_unsub_links(
        self, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Updated")
        body = mail.outbox[0].body
        assert body.count("/unsubscribe/") == 2

    def test_excluded_user_not_notified(
        self, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        SubscriptionExclusion.objects.create(
            user=other_user, page=page_in_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Updated")
        assert len(mail.outbox) == 0

    def test_editor_not_notified(self, user, sub_directory, page_in_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Self edit")
        assert len(mail.outbox) == 0

    def test_both_page_and_dir_subscriber_gets_one_email(
        self, user, other_user, sub_directory, page_in_directory
    ):
        """User with both page and dir sub should get one email (page sub
        takes priority in the mapping)."""
        PageSubscription.objects.create(
            user=other_user, page=page_in_directory
        )
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Updated")
        # Should only get one email — the direct page subscription one
        assert len(mail.outbox) == 1

    def test_security_no_notification_for_private_page(
        self, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        from wiki.pages.models import Page

        page_in_directory.visibility = Page.Visibility.PRIVATE
        page_in_directory.save()
        notify_subscribers(page_in_directory.id, user.id, "Secret update")
        assert len(mail.outbox) == 0

    def test_root_dir_subscriber_notified_for_nested_page(
        self,
        user,
        other_user,
        root_directory,
        sub_directory,
        nested_directory,
        page_in_nested_directory,
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=root_directory
        )
        notify_subscribers(page_in_nested_directory.id, user.id, "Deep update")
        assert len(mail.outbox) == 1

    def test_page_sub_and_dir_sub_different_users(
        self, user, other_user, sub_directory, page_in_directory
    ):
        """Two different users: one page sub, one dir sub."""
        from django.contrib.auth.models import User

        from wiki.users.models import UserProfile

        third = User.objects.create_user(
            username="carol@free.law",
            email="carol@free.law",
            password="testpass",
        )
        UserProfile.objects.create(user=third, display_name="Carol")

        PageSubscription.objects.create(
            user=other_user, page=page_in_directory
        )
        DirectorySubscription.objects.create(
            user=third, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Change")
        assert len(mail.outbox) == 2
        recipients = {mail.outbox[0].to[0], mail.outbox[1].to[0]}
        assert other_user.email in recipients
        assert third.email in recipients

    def test_dir_exclusion_blocks_notification(
        self,
        user,
        other_user,
        root_directory,
        sub_directory,
        page_in_directory,
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=root_directory
        )
        SubscriptionExclusion.objects.create(
            user=other_user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Blocked update")
        assert len(mail.outbox) == 0


class TestNotifySubscribers:
    """Original backward-compatible tests for direct page subscriptions."""

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


# ── Unsubscribe landing/one-click tests ──────────────────────────


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

    def test_dir_token_shows_confirm(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"d:{user.id}:{sub_directory.id}")
        r = client.get(f"/unsubscribe/{token}/")
        assert r.status_code == 200
        assert b"Unsubscribe" in r.content


class TestDirectoryUnsubscribeViaEmail:
    def test_post_removes_dir_subscription(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"d:{user.id}:{sub_directory.id}")
        r = client.post(f"/unsubscribe/{token}/")
        assert r.status_code == 302
        assert not DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).exists()

    def test_page_unsub_creates_exclusion_when_dir_covers(
        self, client, user, sub_directory, page_in_directory
    ):
        """Unsubscribing from page via email link should create exclusion
        if still covered by directory subscription."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        PageSubscription.objects.create(user=user, page=page_in_directory)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page_in_directory.id}")
        r = client.post(f"/unsubscribe/{token}/")
        assert r.status_code == 302
        assert not PageSubscription.objects.filter(
            user=user, page=page_in_directory
        ).exists()
        assert SubscriptionExclusion.objects.filter(
            user=user, page=page_in_directory
        ).exists()


class TestOneClickUnsubscribe:
    def test_page_one_click(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.post(f"/unsubscribe/{token}/one-click/")
        assert r.status_code == 200
        assert not PageSubscription.objects.filter(
            user=user, page=page
        ).exists()

    def test_dir_one_click(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"d:{user.id}:{sub_directory.id}")
        r = client.post(f"/unsubscribe/{token}/one-click/")
        assert r.status_code == 200
        assert not DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).exists()

    def test_page_one_click_creates_exclusion(
        self, client, user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"{user.id}:{page_in_directory.id}")
        r = client.post(f"/unsubscribe/{token}/one-click/")
        assert r.status_code == 200
        assert SubscriptionExclusion.objects.filter(
            user=user, page=page_in_directory
        ).exists()


# ── Integration tests ────────────────────────────────────────────


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

    def test_edit_notifies_directory_subscriber(
        self, client, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        client.force_login(user)
        client.post(
            f"/c/{sub_directory.path}/{page_in_directory.slug}/edit/",
            {
                "title": page_in_directory.title,
                "content": "Updated via dir sub",
                "visibility": "public",
                "editability": "restricted",
                "change_message": "Dir sub test",
                "directory_path": sub_directory.path,
            },
        )
        assert len(mail.outbox) == 1
        assert "Dir sub test" in mail.outbox[0].body


# ── Template context tests ───────────────────────────────────────


class TestDirectoryDetailSubscriptionState:
    def test_subscribed_context(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.get(f"/c/{sub_directory.path}/")
        assert r.context["is_dir_subscribed"] is True

    def test_not_subscribed_context(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get(f"/c/{sub_directory.path}/")
        assert r.context["is_dir_subscribed"] is False


class TestPageDetailSubscriptionState:
    def test_subscribed_via_directory(
        self, client, user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.get(page_in_directory.get_absolute_url())
        assert r.context["is_subscribed"] is True

    def test_not_subscribed(self, client, user, page):
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert r.context["is_subscribed"] is False
