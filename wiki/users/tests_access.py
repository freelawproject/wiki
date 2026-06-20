"""Tests for allowlist tiers and domain-grant lifecycle via the Access UI."""

from django.urls import reverse

from wiki.pages.models import Page, PagePermission
from wiki.users.models import AccessTier, AllowedDomain, AllowedEmail


class TestTierDefaults:
    def test_domain_defaults_to_third_party(self, db):
        d = AllowedDomain.objects.create(domain="x.com", suffix="x")
        assert d.tier == AccessTier.THIRD_PARTY

    def test_email_defaults_to_third_party(self, db):
        e = AllowedEmail.objects.create(email="p@x.com")
        assert e.tier == AccessTier.THIRD_PARTY


class TestDomainGrantLifecycleViews:
    def _add_domain(self, client, tier="third_party"):
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
