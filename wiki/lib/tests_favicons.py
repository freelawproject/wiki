"""Tests for domain-access favicons: fetch/normalize, storage, the
staff-gated serving endpoint, the access-domain annotation, and the daemon
refresh selection."""

import io
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from wiki.directories.models import Directory, DirectoryPermission
from wiki.lib import favicons
from wiki.lib.permissions import annotate_access_domains
from wiki.pages.models import Page, PagePermission, PageRevision
from wiki.users.models import AccessTier, AllowedDomain, UserProfile
from wiki.users.tasks import refresh_domain_favicons


def _png_bytes(color="red", size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def acme(db):
    return AllowedDomain.objects.create(
        domain="acme.com", suffix="acme", tier=AccessTier.GUEST
    )


# --- fetch + normalize --------------------------------------------------


class TestFetchFavicon:
    def test_rasterizes_to_small_png(self):
        raw = _png_bytes(size=(128, 128))
        with mock.patch.object(favicons, "_fetch", return_value=raw):
            out = favicons.fetch_favicon("acme.com")
        assert out is not None
        img = Image.open(io.BytesIO(out))
        assert img.format == "PNG"
        assert max(img.size) <= favicons.FAVICON_SIZE

    def test_uses_link_rel_icon_then_falls_back(self):
        html = b'<html><head><link rel="icon" href="/x.png"></head></html>'
        png = _png_bytes()
        calls = []

        def fake_fetch(url, max_bytes):
            calls.append(url)
            if url.endswith("/x.png"):
                return png
            if url.endswith("/"):
                return html
            raise AssertionError("unexpected url")

        with mock.patch.object(favicons, "_fetch", side_effect=fake_fetch):
            out = favicons.fetch_favicon("acme.com")
        assert out is not None
        assert any(u.endswith("/x.png") for u in calls)

    def test_non_image_returns_none(self):
        with mock.patch.object(favicons, "_fetch", return_value=b"not image"):
            assert favicons.fetch_favicon("acme.com") is None

    def test_fetch_failure_returns_none(self):
        with mock.patch.object(
            favicons, "_fetch", side_effect=OSError("boom")
        ):
            assert favicons.fetch_favicon("acme.com") is None

    def test_ssrf_guard_rejects_private_host(self):
        # _host_is_public must reject loopback/private/link-local.
        with mock.patch.object(
            favicons.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
        ):
            assert favicons._host_is_public("evil.test") is False

    def test_fetch_refuses_non_public_host(self):
        with mock.patch.object(
            favicons, "_host_is_public", return_value=False
        ):
            with pytest.raises(ValueError):
                favicons._fetch("https://acme.com/favicon.ico", 1000)


class TestStoreFavicon:
    def test_stores_bytes_and_timestamp(self, acme):
        with mock.patch.object(
            favicons, "fetch_favicon", return_value=b"PNGDATA"
        ):
            favicons.store_favicon(acme)
        acme.refresh_from_db()
        assert bytes(acme.favicon_data) == b"PNGDATA"
        assert acme.favicon_checked_at is not None
        assert acme.has_favicon is True

    def test_failure_records_attempt_without_data(self, acme):
        with mock.patch.object(favicons, "fetch_favicon", return_value=None):
            favicons.store_favicon(acme)
        acme.refresh_from_db()
        assert acme.favicon_data is None
        assert acme.favicon_checked_at is not None
        assert acme.has_favicon is False


# --- serving endpoint ---------------------------------------------------


class TestDomainFaviconEndpoint:
    def _staff(self):
        u = User.objects.create_user(
            username="s@free.law", email="s@free.law", password="x"
        )
        UserProfile.objects.create(user=u)
        return u  # free.law is staff-tier (seeded)

    def _guest(self, acme):
        u = User.objects.create_user(
            username="g@acme.com", email="g@acme.com", password="x"
        )
        UserProfile.objects.create(user=u)
        return u

    def test_staff_gets_png(self, client, acme):
        acme.favicon_data = _png_bytes()
        acme.save(update_fields=["favicon_data"])
        client.force_login(self._staff())
        r = client.get(
            reverse("domain_favicon", kwargs={"domain": "acme.com"})
        )
        assert r.status_code == 200
        assert r["Content-Type"] == "image/png"

    def test_guest_gets_404(self, client, acme):
        acme.favicon_data = _png_bytes()
        acme.save(update_fields=["favicon_data"])
        client.force_login(self._guest(acme))
        r = client.get(
            reverse("domain_favicon", kwargs={"domain": "acme.com"})
        )
        assert r.status_code == 404

    def test_anonymous_gets_404(self, client, acme):
        acme.favicon_data = _png_bytes()
        acme.save(update_fields=["favicon_data"])
        r = client.get(
            reverse("domain_favicon", kwargs={"domain": "acme.com"})
        )
        assert r.status_code == 404

    def test_missing_favicon_404(self, client, acme):
        client.force_login(self._staff())
        r = client.get(
            reverse("domain_favicon", kwargs={"domain": "acme.com"})
        )
        assert r.status_code == 404


# --- access-domain annotation -------------------------------------------


class TestAnnotateAccessDomains:
    def _page(self, owner, directory=None, slug="p"):
        p = Page.objects.create(
            title=slug,
            slug=slug,
            content="x",
            directory=directory,
            owner=owner,
            created_by=owner,
            updated_by=owner,
        )
        PageRevision.objects.create(
            page=p,
            title=p.title,
            content=p.content,
            change_message="i",
            revision_number=1,
            created_by=owner,
        )
        return p

    def test_inherited_and_direct_grants(self, user, acme):
        root = Directory.objects.create(path="", title="Home")
        parent = Directory.objects.create(
            path="team",
            title="Team",
            parent=root,
            owner=user,
            created_by=user,
        )
        child = Directory.objects.create(
            path="team/sub",
            title="Sub",
            parent=parent,
            owner=user,
            created_by=user,
        )
        DirectoryPermission.objects.create(
            directory=parent,
            grant_domain="acme.com",
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        page = self._page(user, directory=child)

        annotate_access_domains(pages=[page], directories=[child])
        assert [d.domain for d in page.access_domains] == ["acme.com"]
        assert [d.domain for d in child.access_domains] == ["acme.com"]

    def test_dormant_grant_excluded(self, user, acme):
        page = self._page(user)
        PagePermission.objects.create(
            page=page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
            dormant_since=timezone.now(),
        )
        annotate_access_domains(pages=[page])
        assert page.access_domains == []

    def test_removed_domain_excluded(self, user):
        # A grant string with no matching AllowedDomain shows nothing.
        page = self._page(user)
        PagePermission.objects.create(
            page=page,
            grant_domain="gone.example",
            permission_type=PagePermission.PermissionType.VIEW,
        )
        annotate_access_domains(pages=[page])
        assert page.access_domains == []


# --- staff-only rendering ----------------------------------------------


class TestBadgeRenderingIsStaffOnly:
    def test_staff_sees_badge_guest_does_not(self, client, user, acme):
        acme.favicon_data = _png_bytes()
        acme.save(update_fields=["favicon_data"])
        # Internal page shared with acme.com: staff can view (internal), the
        # acme.com guest can view (grant) — but only staff get the badge.
        page = Page.objects.create(
            title="Shared Internal",
            slug="shared-internal",
            content="x",
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INTERNAL,
        )
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message="i",
            revision_number=1,
            created_by=user,
        )
        PagePermission.objects.create(
            page=page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        )
        favicon_url = reverse("domain_favicon", kwargs={"domain": "acme.com"})

        # Staff viewer (user is free.law = staff) sees the favicon badge.
        client.force_login(user)
        r = client.get(page.get_absolute_url())
        assert r.status_code == 200
        assert favicon_url.encode() in r.content

        # Guest from acme.com can view the page but sees no access badge.
        guest = User.objects.create_user(
            username="g@acme.com", email="g@acme.com", password="x"
        )
        UserProfile.objects.create(user=guest)
        client.force_login(guest)
        r2 = client.get(page.get_absolute_url())
        assert r2.status_code == 200
        assert favicon_url.encode() not in r2.content


# --- daemon refresh selection -------------------------------------------


class TestRefreshDomainFavicons:
    def test_selects_unchecked_and_stale_skips_fresh(self, db):
        never = AllowedDomain.objects.create(domain="a.com", suffix="a")
        stale = AllowedDomain.objects.create(
            domain="b.com",
            suffix="b",
            favicon_checked_at=timezone.now() - timezone.timedelta(days=30),
        )
        fresh = AllowedDomain.objects.create(
            domain="c.com", suffix="c", favicon_checked_at=timezone.now()
        )
        seen = []
        with mock.patch.object(
            favicons, "fetch_favicon", side_effect=lambda d: seen.append(d)
        ):
            refresh_domain_favicons()
        assert "a.com" in seen and "b.com" in seen
        assert "c.com" not in seen
        # fresh row untouched
        fresh.refresh_from_db()
        assert fresh.domain == "c.com"
