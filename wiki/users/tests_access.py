"""Tests for allowlist tiers and domain-grant lifecycle via the Access UI."""

from django.core import mail
from django.urls import reverse

from wiki.pages.models import Page, PagePermission
from wiki.users.models import AccessTier, AllowedDomain, AllowedEmail


class TestTierDefaults:
    def test_domain_defaults_to_guest(self, db):
        d = AllowedDomain.objects.create(domain="x.com", suffix="x")
        assert d.tier == AccessTier.GUEST

    def test_email_defaults_to_guest(self, db):
        e = AllowedEmail.objects.create(email="p@x.com")
        assert e.tier == AccessTier.GUEST


class TestDomainGrantLifecycleViews:
    def _add_domain(self, client, tier="guest"):
        return client.post(
            reverse("access_add_domain"),
            {
                "domain": "acme.com",
                "suffix": "acme",
                "tier": tier,
                "note": "",
            },
        )

    def test_remove_retains_and_dormant_then_readd_reactivates(
        self, client, owner_user
    ):
        client.force_login(owner_user)
        self._add_domain(client)
        domain = AllowedDomain.objects.get(domain="acme.com")

        page = Page.objects.create(
            title="Doc",
            slug="doc",
            content="x",
            owner=owner_user,
            created_by=owner_user,
            updated_by=owner_user,
            visibility=Page.Visibility.INTERNAL,
        )
        perm = PagePermission.objects.create(
            page=page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        )

        # Remove the domain: grant is retained but flagged dormant.
        client.post(reverse("access_delete_domain", kwargs={"pk": domain.pk}))
        perm.refresh_from_db()
        assert perm.dormant_since is not None
        assert PagePermission.objects.filter(pk=perm.pk).exists()

        # Re-add the domain: grant reactivates with no re-granting.
        self._add_domain(client)
        perm.refresh_from_db()
        assert perm.dormant_since is None

    def test_can_create_staff_tier_domain(self, client, owner_user):
        client.force_login(owner_user)
        self._add_domain(client, tier="staff")
        assert (
            AllowedDomain.objects.get(domain="acme.com").tier
            == AccessTier.STAFF
        )

    def test_domain_audit_email_includes_tier(self, client, owner_user):
        client.force_login(owner_user)
        mail.outbox.clear()
        self._add_domain(client, tier="staff")
        audit = [m for m in mail.outbox if "allowlist" in m.subject.lower()]
        assert audit
        assert "staff entry" in audit[0].body


class TestGranteeNotification:
    def test_adding_email_notifies_the_grantee(self, client, owner_user):
        client.force_login(owner_user)
        mail.outbox.clear()
        client.post(
            reverse("access_add_email"),
            {"email": "newcomer@example.org", "tier": "guest", "note": ""},
        )
        grantee = [m for m in mail.outbox if m.to == ["newcomer@example.org"]]
        assert len(grantee) == 1
        assert reverse("login") in grantee[0].body

    def test_adding_domain_does_not_email_a_grantee(self, client, owner_user):
        # A domain has no single address, so only the owner/manager audit
        # email goes out — nothing to a grantee.
        client.force_login(owner_user)
        mail.outbox.clear()
        client.post(
            reverse("access_add_domain"),
            {
                "domain": "acme.com",
                "suffix": "acme",
                "tier": "guest",
                "note": "",
            },
        )
        assert all("allowlist" in m.subject.lower() for m in mail.outbox)
