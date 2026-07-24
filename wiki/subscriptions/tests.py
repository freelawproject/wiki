"""Tests for subscriptions: toggle, notify, unsubscribe."""

from datetime import timedelta

import pytest
import time_machine
from django.core import mail
from django.core.signing import Signer
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from wiki.pages.models import Page
from wiki.subscriptions.models import (
    DirectorySubscription,
    EmailSubscription,
    PageSubscription,
    SubscriptionStatus,
)
from wiki.subscriptions.tasks import (
    make_confirm_token,
    notify_subscribers,
    read_confirm_token,
)
from wiki.subscriptions.utils import (
    get_effective_watchers_for_page,
    get_subscriber_info_for_page,
    is_effectively_subscribed_to_directory,
    is_effectively_subscribed_to_page,
)

S = SubscriptionStatus.SUBSCRIBED
U = SubscriptionStatus.UNSUBSCRIBED


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
        assert str(ds) == f"{user} → {sub_directory} (subscribed)"

    def test_create_unsubscribed(self, user, sub_directory):
        ds = DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        assert str(ds) == f"{user} → {sub_directory} (unsubscribed)"

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


class TestPageSubscriptionModel:
    def test_create(self, user, page):
        ps = PageSubscription.objects.create(user=user, page=page)
        assert ps.pk is not None
        assert str(ps) == f"{user} → {page} (subscribed)"

    def test_create_unsubscribed(self, user, page):
        ps = PageSubscription.objects.create(user=user, page=page, status=U)
        assert str(ps) == f"{user} → {page} (unsubscribed)"


# ── Utility function tests ───────────────────────────────────────


class TestGetSubscriberInfoForPage:
    def test_page_sub_only(self, user, page):
        PageSubscription.objects.create(user=user, page=page)
        page_subs, dir_subs = get_subscriber_info_for_page(page)
        assert user.id in page_subs
        assert not dir_subs

    def test_page_unsub_not_included(self, user, page):
        PageSubscription.objects.create(user=user, page=page, status=U)
        page_subs, dir_subs = get_subscriber_info_for_page(page)
        assert user.id not in page_subs
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

    def test_dir_unsub_blocks(self, user, sub_directory, page_in_directory):
        """An UNSUBSCRIBED directory record blocks inheritance."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        _, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id not in dir_subs

    def test_page_unsub_overrides_dir_sub(
        self, user, sub_directory, page_in_directory
    ):
        """Page-level UNSUBSCRIBED overrides directory SUBSCRIBED."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        PageSubscription.objects.create(
            user=user, page=page_in_directory, status=U
        )
        page_subs, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id not in page_subs
        assert user.id not in dir_subs

    def test_closer_dir_overrides_parent(
        self,
        user,
        root_directory,
        sub_directory,
        nested_directory,
        page_in_nested_directory,
    ):
        """User subscribes to root, unsubscribes from engineering,
        subscribes to devops. Should still get notifications for devops
        pages."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        DirectorySubscription.objects.create(
            user=user, directory=nested_directory
        )
        _, dir_subs = get_subscriber_info_for_page(page_in_nested_directory)
        assert user.id in dir_subs
        assert dir_subs[user.id] == nested_directory

    def test_page_sub_takes_priority_over_dir_sub(
        self, user, sub_directory, page_in_directory
    ):
        """Page-level SUBSCRIBED wins; user only in page_sub_user_ids."""
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        page_subs, dir_subs = get_subscriber_info_for_page(page_in_directory)
        assert user.id in page_subs
        assert user.id not in dir_subs

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

    def test_direct_unsub(self, user, page):
        PageSubscription.objects.create(user=user, page=page, status=U)
        assert not is_effectively_subscribed_to_page(user, page)

    def test_dir_sub(self, user, sub_directory, page_in_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        assert is_effectively_subscribed_to_page(user, page_in_directory)

    def test_page_unsub_overrides_dir_sub(
        self, user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        PageSubscription.objects.create(
            user=user, page=page_in_directory, status=U
        )
        assert not is_effectively_subscribed_to_page(user, page_in_directory)

    def test_not_subscribed(self, user, page):
        assert not is_effectively_subscribed_to_page(user, page)

    def test_dir_unsub_blocks_parent_sub(
        self, user, root_directory, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        assert not is_effectively_subscribed_to_page(user, page_in_directory)


class TestIsEffectivelySubscribedToDirectory:
    def test_direct(self, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        assert is_effectively_subscribed_to_directory(user, sub_directory)

    def test_direct_unsub(self, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        assert not is_effectively_subscribed_to_directory(user, sub_directory)

    def test_inherited(self, user, root_directory, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        assert is_effectively_subscribed_to_directory(user, sub_directory)

    def test_not_subscribed(self, user, sub_directory):
        assert not is_effectively_subscribed_to_directory(user, sub_directory)

    def test_unsub_overrides_parent(self, user, root_directory, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        assert not is_effectively_subscribed_to_directory(user, sub_directory)

    def test_re_subscribe_below_unsub(
        self, user, root_directory, sub_directory, nested_directory
    ):
        """Subscribe root, unsub engineering, subscribe devops → devops
        is subscribed."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        DirectorySubscription.objects.create(
            user=user, directory=nested_directory
        )
        assert is_effectively_subscribed_to_directory(user, nested_directory)


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
        """Subscribe to page → subscribe to parent dir →
        unsub from dir → still subscribed to page."""
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        # Unsubscribe from directory
        DirectorySubscription.objects.filter(
            user=user, directory=sub_directory
        ).update(status=U)
        # Page subscription should still be active
        assert is_effectively_subscribed_to_page(user, page_in_directory)

    def test_dir_sub_then_unsub_page(
        self, user, sub_directory, page_in_directory
    ):
        """Subscribe to dir, override page to unsubscribed →
        no notifications for that page."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        PageSubscription.objects.create(
            user=user, page=page_in_directory, status=U
        )
        assert not is_effectively_subscribed_to_page(user, page_in_directory)

    def test_dir_sub_then_unsub_subdir(
        self,
        user,
        root_directory,
        sub_directory,
        nested_directory,
        page_in_nested_directory,
    ):
        """Subscribe to root, override devops to unsubscribed →
        no notifications for pages in devops."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=nested_directory, status=U
        )
        assert not is_effectively_subscribed_to_page(
            user, page_in_nested_directory
        )

    def test_inheritance_chain(
        self,
        user,
        root_directory,
        sub_directory,
        nested_directory,
        page_in_nested_directory,
        page_in_directory,
    ):
        """Subscribe root, unsub engineering → pages in engineering are
        unsubscribed, but re-subscribing devops overrides for that subtree."""
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        assert not is_effectively_subscribed_to_page(user, page_in_directory)
        assert not is_effectively_subscribed_to_page(
            user, page_in_nested_directory
        )

        DirectorySubscription.objects.create(
            user=user, directory=nested_directory
        )
        assert not is_effectively_subscribed_to_page(user, page_in_directory)
        assert is_effectively_subscribed_to_page(
            user, page_in_nested_directory
        )


# ── View tests ───────────────────────────────────────────────────


class TestToggleSubscription:
    def test_subscribe_to_page(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("page_subscribe", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page, status=S
        ).exists()

    def test_unsubscribe_from_page(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        client.force_login(user)
        r = client.post(
            reverse("page_subscribe", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page, status=U
        ).exists()

    def test_htmx_subscribe_returns_button(self, client, user, page):
        client.force_login(user)
        r = client.post(
            reverse("page_subscribe", kwargs={"path": page.content_path}),
            HTTP_HX_REQUEST="true",
        )
        assert r.status_code == 200
        assert b"Unsubscribe" in r.content

    def test_htmx_unsubscribe_returns_button(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        client.force_login(user)
        r = client.post(
            reverse("page_subscribe", kwargs={"path": page.content_path}),
            HTTP_HX_REQUEST="true",
        )
        assert b"Subscribe" in r.content

    def test_requires_login(self, client, page):
        r = client.post(
            reverse("page_subscribe", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_get_returns_404(self, client, user, page):
        client.force_login(user)
        r = client.get(
            reverse("page_subscribe", kwargs={"path": page.content_path})
        )
        assert r.status_code == 404

    def test_unsub_page_when_dir_subscribed(
        self, client, user, sub_directory, page_in_directory
    ):
        """Unsubscribing from a page when subscribed via directory
        should create an UNSUBSCRIBED page override."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "page_subscribe",
                kwargs={
                    "path": f"{sub_directory.path}/{page_in_directory.slug}"
                },
            )
        )
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory, status=U
        ).exists()

    def test_subscribe_after_unsub(
        self, client, user, sub_directory, page_in_directory
    ):
        """Subscribing to a page that has UNSUBSCRIBED override should
        flip it to SUBSCRIBED."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        PageSubscription.objects.create(
            user=user, page=page_in_directory, status=U
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "page_subscribe",
                kwargs={
                    "path": f"{sub_directory.path}/{page_in_directory.slug}"
                },
            )
        )
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory, status=S
        ).exists()

    def test_unsub_both_direct_and_dir(
        self, client, user, sub_directory, page_in_directory
    ):
        """If user has both direct page sub and dir sub, unsubscribe
        sets page override to UNSUBSCRIBED."""
        PageSubscription.objects.create(user=user, page=page_in_directory)
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "page_subscribe",
                kwargs={
                    "path": f"{sub_directory.path}/{page_in_directory.slug}"
                },
            )
        )
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory, status=U
        ).exists()


class TestToggleDirectorySubscription:
    def test_subscribe_to_directory(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory, status=S
        ).exists()

    def test_unsubscribe_from_directory(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory, status=U
        ).exists()

    def test_subscribe_root(self, client, user, root_directory):
        client.force_login(user)
        r = client.post(
            reverse("directory_subscribe_root"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert DirectorySubscription.objects.filter(
            user=user, directory=root_directory, status=S
        ).exists()

    def test_requires_login(self, client, sub_directory):
        r = client.post(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            )
        )
        assert r.status_code == 302
        assert reverse("login") in r.url

    def test_get_returns_404(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            )
        )
        assert r.status_code == 404

    def test_unsub_creates_override_when_parent_subscribed(
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
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        # Should flip to UNSUBSCRIBED
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory, status=U
        ).exists()

    def test_subscribe_flips_unsub_to_sub(
        self, client, user, root_directory, sub_directory
    ):
        DirectorySubscription.objects.create(
            user=user, directory=root_directory
        )
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory, status=U
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert r.status_code == 204
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory, status=S
        ).exists()

    def test_non_ajax_redirects(self, client, user, sub_directory):
        client.force_login(user)
        r = client.post(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            )
        )
        assert r.status_code == 302

    def test_non_ajax_unsub_redirects(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "directory_subscribe",
                kwargs={"path": sub_directory.path},
            )
        )
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

    def test_unsub_user_not_notified(
        self, user, other_user, sub_directory, page_in_directory
    ):
        """UNSUBSCRIBED page override blocks notification."""
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        PageSubscription.objects.create(
            user=other_user, page=page_in_directory, status=U
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
        takes priority)."""
        PageSubscription.objects.create(
            user=other_user, page=page_in_directory
        )
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        notify_subscribers(page_in_directory.id, user.id, "Updated")
        assert len(mail.outbox) == 1
        # Page sub takes priority → simple unsub email (1 unsub link)
        body = mail.outbox[0].body
        assert body.count("/unsubscribe/") == 1

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

    def test_dir_unsub_blocks_notification(
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
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory, status=U
        )
        notify_subscribers(page_in_directory.id, user.id, "Blocked update")
        assert len(mail.outbox) == 0


class TestNotifySubscribers:
    """Tests for direct page subscriptions."""

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
        r = client.get(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 200
        assert b"Unsubscribe" in r.content

    def test_valid_token_post_unsubscribes(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.post(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page, status=U
        ).exists()

    def test_invalid_token_redirects(self, client, db):
        r = client.get(reverse("unsubscribe", kwargs={"token": "bad-token"}))
        assert r.status_code == 302

    def test_dir_token_shows_confirm(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"d:{user.id}:{sub_directory.id}")
        r = client.get(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 200
        assert b"Unsubscribe" in r.content


class TestDirectoryUnsubscribeViaEmail:
    def test_post_sets_dir_unsubscribed(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"d:{user.id}:{sub_directory.id}")
        r = client.post(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 302
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory, status=U
        ).exists()

    def test_page_unsub_creates_override(
        self, client, user, sub_directory, page_in_directory
    ):
        """Unsubscribing from page via email sets page to UNSUBSCRIBED."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        PageSubscription.objects.create(user=user, page=page_in_directory)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page_in_directory.id}")
        r = client.post(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory, status=U
        ).exists()


class TestOneClickUnsubscribe:
    def test_page_one_click(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.post(
            reverse("unsubscribe_one_click", kwargs={"token": token})
        )
        assert r.status_code == 200
        assert PageSubscription.objects.filter(
            user=user, page=page, status=U
        ).exists()

    def test_dir_one_click(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"d:{user.id}:{sub_directory.id}")
        r = client.post(
            reverse("unsubscribe_one_click", kwargs={"token": token})
        )
        assert r.status_code == 200
        assert DirectorySubscription.objects.filter(
            user=user, directory=sub_directory, status=U
        ).exists()

    def test_page_one_click_creates_override(
        self, client, user, sub_directory, page_in_directory
    ):
        """One-click page unsub when covered by dir sub creates
        UNSUBSCRIBED override."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        signer = Signer()
        token = signer.sign(f"{user.id}:{page_in_directory.id}")
        r = client.post(
            reverse("unsubscribe_one_click", kwargs={"token": token})
        )
        assert r.status_code == 200
        assert PageSubscription.objects.filter(
            user=user, page=page_in_directory, status=U
        ).exists()


class TestUnsubscribeForDeletedPage:
    """Delete notifications link to unsubscribe URLs that are clicked after
    the page is soft-deleted, so the handlers must resolve soft-deleted
    pages (Page.all_objects) rather than silently no-op."""

    def test_one_click_unsubscribes_deleted_page(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        page.soft_delete(user)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.post(
            reverse("unsubscribe_one_click", kwargs={"token": token})
        )
        assert r.status_code == 200
        assert PageSubscription.objects.filter(
            user=user, page=page, status=U
        ).exists()

    def test_landing_get_renders_for_deleted_page(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        page.soft_delete(user)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.get(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 200

    def test_landing_post_unsubscribes_deleted_page(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page)
        page.soft_delete(user)
        signer = Signer()
        token = signer.sign(f"{user.id}:{page.id}")
        r = client.post(reverse("unsubscribe", kwargs={"token": token}))
        assert r.status_code == 302
        assert PageSubscription.objects.filter(
            user=user, page=page, status=U
        ).exists()


# ── Integration tests ────────────────────────────────────────────


class TestRevertNotifiesSubscribers:
    """Integration: reverting a page sends notification emails."""

    def test_revert_sends_notification(self, client, user, other_user, page):
        # Create revision 2 by editing
        client.force_login(user)
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
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
        client.post(
            reverse(
                "page_revert",
                kwargs={"path": page.slug, "rev_num": 1},
            )
        )
        assert len(mail.outbox) == 1
        assert "Reverted to version 1" in mail.outbox[0].body


class TestEditNotifiesSubscribers:
    """Integration: editing a page sends notification emails."""

    def test_edit_sends_notification(self, client, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        client.force_login(user)
        client.post(
            reverse("page_edit", kwargs={"path": page.content_path}),
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
            reverse(
                "page_edit",
                kwargs={
                    "path": f"{sub_directory.path}/{page_in_directory.slug}"
                },
            ),
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


class TestNotifyActionWording:
    """The action argument controls subject/body wording and links."""

    def test_created_action(self, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        notify_subscribers(page.id, user.id, "Add new page", action="created")
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert "was created" in msg.subject
        assert "created" in msg.body
        # A new page has a working View link but no diff.
        assert page.get_absolute_url() in msg.body
        assert "Diff:" not in msg.body

    def test_deleted_action(self, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        notify_subscribers(page.id, user.id, "", action="deleted")
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert "was deleted" in msg.subject
        assert "deleted" in msg.body
        # A deleted page would 404, so don't link to it or a diff.
        assert "View:" not in msg.body
        assert "Diff:" not in msg.body

    def test_default_action_is_updated(self, user, other_user, page):
        PageSubscription.objects.create(user=other_user, page=page)
        notify_subscribers(page.id, user.id, "Change")
        assert "was updated" in mail.outbox[0].subject


class TestCreateNotifiesSubscribers:
    """Integration: creating a page notifies directory subscribers."""

    def test_create_notifies_directory_subscriber(
        self, client, user, other_user, sub_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Brand New Page",
                "content": "Fresh content",
                "visibility": "public",
                "editability": "inherit",
                "in_sitemap": "inherit",
                "in_llms_txt": "inherit",
                "change_message": "Add new page",
                "directory_path": sub_directory.path,
                "directory_titles": "{}",
            },
        )
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        assert other_user.email in mail.outbox[0].to
        assert "was created" in mail.outbox[0].subject

    def test_create_does_not_notify_creator(self, client, user, sub_directory):
        """The creator is auto-subscribed but shouldn't email themselves."""
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse("page_create"),
            {
                "title": "Solo Page",
                "content": "Content",
                "visibility": "public",
                "editability": "inherit",
                "in_sitemap": "inherit",
                "in_llms_txt": "inherit",
                "change_message": "Add new page",
                "directory_path": sub_directory.path,
                "directory_titles": "{}",
            },
        )
        assert r.status_code == 302
        assert len(mail.outbox) == 0


class TestDeleteNotifiesSubscribers:
    """Integration: deleting a page notifies subscribers."""

    def test_delete_notifies_page_subscriber(
        self, client, user, other_user, page
    ):
        PageSubscription.objects.create(user=other_user, page=page)
        client.force_login(user)
        r = client.post(
            reverse("page_delete", kwargs={"path": page.content_path})
        )
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        assert other_user.email in mail.outbox[0].to
        assert "was deleted" in mail.outbox[0].subject

    def test_delete_notifies_directory_subscriber(
        self, client, user, other_user, sub_directory, page_in_directory
    ):
        DirectorySubscription.objects.create(
            user=other_user, directory=sub_directory
        )
        client.force_login(user)
        r = client.post(
            reverse(
                "page_delete",
                kwargs={"path": page_in_directory.content_path},
            )
        )
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        assert other_user.email in mail.outbox[0].to


# ── Template context tests ───────────────────────────────────────


class TestDirectoryDetailSubscriptionState:
    def test_subscribed_context(self, client, user, sub_directory):
        DirectorySubscription.objects.create(
            user=user, directory=sub_directory
        )
        client.force_login(user)
        r = client.get(
            reverse(
                "resolve_path",
                kwargs={"path": f"{sub_directory.path}/"},
            )
        )
        assert r.context["is_dir_subscribed"] is True

    def test_not_subscribed_context(self, client, user, sub_directory):
        client.force_login(user)
        r = client.get(
            reverse(
                "resolve_path",
                kwargs={"path": f"{sub_directory.path}/"},
            )
        )
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


# ── Anonymous email subscriptions ────────────────────────────────


@pytest.fixture
def public_history_page(page):
    page.history_is_public = True
    page.save(update_fields=["history_is_public"])
    return page


def _subscribe_url(page):
    return reverse("page_email_subscribe", kwargs={"path": page.content_path})


class TestEmailSubscribeView:
    def test_form_renders(self, client, public_history_page):
        r = client.get(_subscribe_url(public_history_page))
        assert r.status_code == 200
        assert b"Send Confirmation Email" in r.content

    def test_404_when_history_not_public(self, client, page):
        r = client.get(_subscribe_url(page))
        assert r.status_code == 404

    def test_404_when_page_not_anonymously_viewable(
        self, client, private_page
    ):
        """Public history on a private page must not accept subscribers."""
        private_page.history_is_public = True
        private_page.save(update_fields=["history_is_public"])
        r = client.get(_subscribe_url(private_page))
        assert r.status_code == 404

    def test_post_sends_single_confirmation(self, client, public_history_page):
        r = client.post(
            _subscribe_url(public_history_page),
            {"email": "reader@example.com"},
        )
        assert r.status_code == 200
        assert b"Check Your Email" in r.content
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["reader@example.com"]
        assert "Confirm" in mail.outbox[0].body
        # No row until the link is confirmed (double opt-in).
        assert EmailSubscription.objects.count() == 0

    def test_email_normalized_in_token(self, client, public_history_page):
        client.post(
            _subscribe_url(public_history_page),
            {"email": "  Reader@Example.COM "},
        )
        token = mail.outbox[0].body.split("Confirm: ")[1].split("\n")[0]
        token = token.rstrip("/").rsplit("/", 1)[-1]
        payload = read_confirm_token(token)
        assert payload["e"] == "reader@example.com"
        assert payload["p"] == public_history_page.id

    def test_honeypot_pretends_success_sends_nothing(
        self, client, public_history_page
    ):
        r = client.post(
            _subscribe_url(public_history_page),
            {"email": "bot@example.com", "website": "spam.example"},
        )
        assert r.status_code == 200
        assert b"Check Your Email" in r.content
        assert len(mail.outbox) == 0

    def test_invalid_email_rerenders_form(self, client, public_history_page):
        r = client.post(
            _subscribe_url(public_history_page), {"email": "not-an-email"}
        )
        assert r.status_code == 200
        assert b"Send Confirmation Email" in r.content
        assert len(mail.outbox) == 0

    @override_settings(RATELIMIT_ENABLE=True)
    def test_post_rate_limited_per_ip(self, client, public_history_page):
        for _ in range(5):
            r = client.post(
                _subscribe_url(public_history_page),
                {"email": "reader@example.com"},
            )
            assert r.status_code == 200
        r = client.post(
            _subscribe_url(public_history_page),
            {"email": "reader@example.com"},
        )
        assert r.status_code == 429


class TestEmailSubscribeConfirm:
    def _confirm_url(self, page, email="reader@example.com"):
        token = make_confirm_token(page, email)
        return reverse("email_subscribe_confirm", kwargs={"token": token})

    def test_get_shows_button_creates_nothing(
        self, client, public_history_page
    ):
        r = client.get(self._confirm_url(public_history_page))
        assert r.status_code == 200
        assert b"Confirm Subscription" in r.content
        assert EmailSubscription.objects.count() == 0

    def test_post_creates_subscription(self, client, public_history_page):
        r = client.post(self._confirm_url(public_history_page))
        assert r.status_code == 200
        sub = EmailSubscription.objects.get()
        assert sub.page == public_history_page
        assert sub.email == "reader@example.com"

    def test_post_idempotent(self, client, public_history_page):
        url = self._confirm_url(public_history_page)
        client.post(url)
        client.post(url)
        assert EmailSubscription.objects.count() == 1

    def test_tampered_token_rejected(self, client, db):
        url = reverse(
            "email_subscribe_confirm", kwargs={"token": "garbage:token"}
        )
        r = client.get(url)
        assert r.status_code == 400
        assert b"Invalid Link" in r.content

    def test_expired_token_rejected(self, client, public_history_page):
        url = self._confirm_url(public_history_page)
        with time_machine.travel(timezone.now() + timedelta(days=4)):
            r = client.get(url)
        assert r.status_code == 400
        assert b"Link Expired" in r.content
        assert EmailSubscription.objects.count() == 0

    def test_flag_toggled_off_before_confirm(
        self, client, public_history_page
    ):
        url = self._confirm_url(public_history_page)
        public_history_page.history_is_public = False
        public_history_page.save(update_fields=["history_is_public"])
        r = client.post(url)
        assert r.status_code == 404
        assert EmailSubscription.objects.count() == 0


class TestEmailUnsubscribe:
    @pytest.fixture
    def subscription(self, public_history_page):
        return EmailSubscription.objects.create(
            page=public_history_page, email="reader@example.com"
        )

    def _token(self, subscription):
        return Signer().sign(f"e:{subscription.id}")

    def test_landing_get_then_post_deletes(self, client, subscription):
        url = reverse(
            "unsubscribe", kwargs={"token": self._token(subscription)}
        )
        r = client.get(url)
        assert r.status_code == 200
        assert b"Confirm Unsubscribe" in r.content
        assert EmailSubscription.objects.count() == 1

        r = client.post(url)
        assert r.status_code == 302
        assert EmailSubscription.objects.count() == 0

    def test_landing_idempotent_after_delete(self, client, subscription):
        url = reverse(
            "unsubscribe", kwargs={"token": self._token(subscription)}
        )
        subscription.delete()
        r = client.get(url)
        assert r.status_code == 200
        assert b"already unsubscribed" in r.content

    def test_one_click_deletes_without_csrf(self, client, subscription):
        url = reverse(
            "unsubscribe_one_click",
            kwargs={"token": self._token(subscription)},
        )
        r = client.post(url)
        assert r.status_code == 200
        assert EmailSubscription.objects.count() == 0

    def test_one_click_bad_signature(self, client, db):
        url = reverse("unsubscribe_one_click", kwargs={"token": "e:1:junk"})
        r = client.post(url)
        assert r.status_code == 400

    def test_legacy_page_token_still_parses(self, client, user, page):
        PageSubscription.objects.create(user=user, page=page, status=S)
        token = Signer().sign(f"{user.id}:{page.id}")
        url = reverse("unsubscribe_one_click", kwargs={"token": token})
        r = client.post(url)
        assert r.status_code == 200
        sub = PageSubscription.objects.get(user=user, page=page)
        assert sub.status == U


class TestNotifyEmailSubscribers:
    @pytest.fixture
    def subscription(self, public_history_page):
        return EmailSubscription.objects.create(
            page=public_history_page, email="reader@example.com"
        )

    def _notify(self, page, editor, **kwargs):
        kwargs.setdefault("prev_rev", 1)
        kwargs.setdefault("new_rev", 2)
        notify_subscribers(page.id, editor.id, "tweaked", **kwargs)

    def test_email_subscriber_notified(
        self, user, public_history_page, subscription
    ):
        self._notify(public_history_page, user)
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["reader@example.com"]
        assert "subscribed to email updates" in msg.body
        assert "List-Unsubscribe" in msg.extra_headers
        assert (
            msg.extra_headers["List-Unsubscribe-Post"]
            == "List-Unsubscribe=One-Click"
        )

    def test_unsubscribe_token_in_email_works(
        self, client, user, public_history_page, subscription
    ):
        self._notify(public_history_page, user)
        body = mail.outbox[0].body
        unsub_url = body.split("Unsubscribe: ")[1].split("\n")[0]
        r = client.post(unsub_url)
        assert r.status_code == 302
        assert EmailSubscription.objects.count() == 0

    def test_paused_when_history_not_public(
        self, user, public_history_page, subscription
    ):
        public_history_page.history_is_public = False
        public_history_page.save(update_fields=["history_is_public"])
        self._notify(public_history_page, user)
        assert len(mail.outbox) == 0
        # Pause, not delete: the row survives for later re-enabling.
        assert EmailSubscription.objects.count() == 1

    def test_paused_when_page_not_anonymously_viewable(
        self, user, public_history_page, subscription
    ):
        public_history_page.visibility = Page.Visibility.PRIVATE
        public_history_page.save(update_fields=["visibility"])
        self._notify(public_history_page, user)
        assert len(mail.outbox) == 0
        assert EmailSubscription.objects.count() == 1

    def test_deduped_against_account_subscriber(
        self, user, other_user, public_history_page
    ):
        PageSubscription.objects.create(
            user=other_user, page=public_history_page, status=S
        )
        EmailSubscription.objects.create(
            page=public_history_page, email=other_user.email.lower()
        )
        self._notify(public_history_page, user)
        # One mail via the account subscription, none for the duplicate.
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [other_user.email]

    def test_editor_own_address_skipped(self, user, public_history_page):
        EmailSubscription.objects.create(
            page=public_history_page, email=user.email.lower()
        )
        self._notify(public_history_page, user)
        assert len(mail.outbox) == 0

    def test_deleted_action_has_no_links(
        self, user, public_history_page, subscription
    ):
        notify_subscribers(
            public_history_page.id, user.id, "", action="deleted"
        )
        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert "View:" not in body
        assert "Diff:" not in body
        assert "Unsubscribe:" in body
