"""Tests for the staff/guest access model and additive grants.

Covers the heart of the "internal = staff, grants are additive" change:
is_internal_user resolution, grants that reveal internal/private content
without changing visibility, owner-only management, the viewable_pages_q ⇔
can_view_page agreement, and domain-grant retention/dormancy.
"""

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.utils import timezone

from wiki.directories.models import Directory, DirectoryPermission
from wiki.lib.access import is_internal_user, resolve_tier
from wiki.lib.markdown import render_markdown
from wiki.lib.permissions import (
    can_administer_directory,
    can_administer_page,
    can_edit_page,
    can_view_directory,
    can_view_page,
    mark_domain_grants_dormant,
    reactivate_domain_grants,
    viewable_pages_q,
)
from wiki.pages.models import Page, PagePermission, PageRevision
from wiki.users.models import (
    AccessTier,
    AllowedDomain,
    AllowedEmail,
    UserProfile,
)


def _make_user(email, **flags):
    u = User.objects.create_user(username=email, email=email, **flags)
    UserProfile.objects.create(user=u)
    return u


@pytest.fixture
def acme(db):
    """A guest domain (not staff)."""
    return AllowedDomain.objects.create(
        domain="acme.com", suffix="acme", tier=AccessTier.GUEST
    )


@pytest.fixture
def carol(acme):
    """A guest user @acme.com."""
    return _make_user("carol@acme.com")


@pytest.fixture
def internal_page(user):
    """An internal-visibility page owned by the staff `user`."""
    p = Page.objects.create(
        title="Internal Doc",
        slug="internal-doc",
        content="staff stuff",
        owner=user,
        created_by=user,
        updated_by=user,
        visibility=Page.Visibility.INTERNAL,
        editability=Page.Editability.INTERNAL,
    )
    PageRevision.objects.create(
        page=p,
        title=p.title,
        content=p.content,
        change_message="init",
        revision_number=1,
        created_by=user,
    )
    return p


# --- is_internal_user ---------------------------------------------------


class TestIsInternalUser:
    def test_staff_domain_is_internal(self, user):
        # free.law is seeded staff by migration 0005.
        assert is_internal_user(user) is True

    def test_guest_domain_is_not_internal(self, carol):
        assert is_internal_user(carol) is False

    def test_individual_email_overrides_domain(self, acme):
        AllowedEmail.objects.create(
            email="vip@acme.com", tier=AccessTier.STAFF
        )
        vip = _make_user("vip@acme.com")
        assert is_internal_user(vip) is True

    def test_manager_is_always_internal(self, acme):
        mgr = _make_user("mgr@acme.com", is_staff=True)
        assert is_internal_user(mgr) is True

    def test_system_owner_is_internal(self, owner_user):
        assert is_internal_user(owner_user) is True

    def test_unknown_address_is_not_internal(self, db):
        stranger = _make_user("nobody@nowhere.test")
        assert is_internal_user(stranger) is False

    def test_resolve_tier_prefers_email_over_domain(self, acme):
        AllowedEmail.objects.create(
            email="vip@acme.com", tier=AccessTier.STAFF
        )
        assert resolve_tier("vip@acme.com") == AccessTier.STAFF
        assert resolve_tier("rando@acme.com") == AccessTier.GUEST
        assert resolve_tier("x@nowhere.test") is None


# --- additive grants on internal/private content ------------------------


class TestAdditiveGrants:
    def test_guest_cannot_view_internal_without_grant(
        self, carol, internal_page
    ):
        assert can_view_page(carol, internal_page) is False

    def test_domain_grant_reveals_internal_page_unchanged(
        self, carol, internal_page
    ):
        PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        )
        assert can_view_page(carol, internal_page) is True
        # Visibility is untouched — still internal.
        internal_page.refresh_from_db()
        assert internal_page.visibility == Page.Visibility.INTERNAL

    def test_individual_grant_reveals_page(self, carol, internal_page):
        PagePermission.objects.create(
            page=internal_page,
            user=carol,
            permission_type=PagePermission.PermissionType.VIEW,
        )
        assert can_view_page(carol, internal_page) is True

    def test_ancestor_directory_grant_reveals_page(self, carol, user):
        parent = Directory.objects.create(
            path="shared",
            title="Shared",
            parent=Directory.objects.create(path="", title="Home"),
            owner=user,
            created_by=user,
            visibility=Directory.Visibility.PRIVATE,
        )
        page = Page.objects.create(
            title="Nested",
            slug="nested",
            content="x",
            directory=parent,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.PRIVATE,
        )
        assert can_view_page(carol, page) is False
        DirectoryPermission.objects.create(
            directory=parent,
            grant_domain="acme.com",
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )
        assert can_view_page(carol, page) is True
        assert can_view_directory(carol, parent) is True

    def test_view_grant_does_not_confer_edit(self, carol, internal_page):
        PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        )
        assert can_view_page(carol, internal_page) is True
        assert can_edit_page(carol, internal_page) is False

    def test_edit_grant_confers_edit_not_admin(self, carol, internal_page):
        PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.EDIT,
        )
        assert can_edit_page(carol, internal_page) is True
        assert can_administer_page(carol, internal_page) is False

    def test_owner_grant_confers_admin(self, carol, internal_page):
        PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.OWNER,
        )
        assert can_administer_page(carol, internal_page) is True


# --- owner-only management ----------------------------------------------


class TestOwnerOnlyManagement:
    def test_plain_editor_is_not_administrator(self, internal_page):
        """A staff member with only internal-editability edit rights (no
        ownership) cannot administer the page."""
        editor = _make_user("dave@free.law")  # staff tier, but not owner
        assert can_edit_page(editor, internal_page) is True
        assert can_administer_page(editor, internal_page) is False

    def test_page_owner_can_administer(self, user, internal_page):
        assert can_administer_page(user, internal_page) is True

    def test_directory_owner_can_administer(self, user, sub_directory):
        assert can_administer_directory(user, sub_directory) is True

    def test_manager_is_not_auto_administrator(self, acme, internal_page):
        mgr = _make_user("mgr@acme.com", is_staff=True)
        # Manager is internal (can view/edit internal) but not an owner.
        assert can_administer_page(mgr, internal_page) is False


# --- viewable_pages_q mirrors can_view_page -----------------------------


class TestViewableQueryAgreement:
    def test_query_matches_can_view_for_guest(self, carol, user):
        root = Directory.objects.create(path="", title="Home")
        priv_dir = Directory.objects.create(
            path="p",
            title="P",
            parent=root,
            owner=user,
            created_by=user,
            visibility=Directory.Visibility.PRIVATE,
        )

        def mk(slug, vis, directory=None):
            return Page.objects.create(
                title=slug,
                slug=slug,
                content="x",
                directory=directory,
                owner=user,
                created_by=user,
                updated_by=user,
                visibility=vis,
            )

        pub = mk("pub", Page.Visibility.PUBLIC)
        internal = mk("int", Page.Visibility.INTERNAL)
        priv = mk("priv", Page.Visibility.PRIVATE)
        granted = mk("granted", Page.Visibility.INTERNAL)
        in_priv_dir = mk("indir", Page.Visibility.PRIVATE, priv_dir)

        PagePermission.objects.create(
            page=granted,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        )
        DirectoryPermission.objects.create(
            directory=priv_dir,
            grant_domain="acme.com",
            permission_type=DirectoryPermission.PermissionType.VIEW,
        )

        all_pages = [pub, internal, priv, granted, in_priv_dir]
        from_query = set(
            Page.objects.filter(viewable_pages_q(carol))
            .distinct()
            .values_list("id", flat=True)
        )
        from_func = {p.id for p in all_pages if can_view_page(carol, p)}
        assert from_query == from_func
        # Guest sees: public, the granted internal page, and the page in
        # the granted private directory — not the ungranted internal/private.
        assert from_func == {pub.id, granted.id, in_priv_dir.id}

    def test_staff_still_sees_internal(self, user, internal_page):
        ids = set(
            Page.objects.filter(viewable_pages_q(user)).values_list(
                "id", flat=True
            )
        )
        assert internal_page.id in ids


# --- domain-grant retention / dormancy ----------------------------------


class TestDomainGrantDormancy:
    def test_mark_and_reactivate(self, internal_page):
        perm = PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
        )
        mark_domain_grants_dormant("acme.com")
        perm.refresh_from_db()
        assert perm.dormant_since is not None

        reactivate_domain_grants("acme.com")
        perm.refresh_from_db()
        assert perm.dormant_since is None

    def test_mark_does_not_reset_existing_dormant_clock(self, internal_page):
        old = timezone.now() - timezone.timedelta(days=30)
        perm = PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
            dormant_since=old,
        )
        mark_domain_grants_dormant("acme.com")
        perm.refresh_from_db()
        assert perm.dormant_since == old

    def test_dormant_grant_still_matches(self, carol, internal_page):
        """A dormant grant still matches in checks — login is the real gate."""
        PagePermission.objects.create(
            page=internal_page,
            grant_domain="acme.com",
            permission_type=PagePermission.PermissionType.VIEW,
            dormant_since=timezone.now(),
        )
        assert can_view_page(carol, internal_page) is True


# --- wiki-link rendering must not leak non-viewable titles --------------


class TestWikiLinkViewerGating:
    def test_guest_does_not_see_internal_title(self, carol, internal_page):
        md = f"See #{internal_page.slug} for details."
        html = render_markdown(md, viewer=carol)
        assert internal_page.title not in html
        assert "Page not found" in html

    def test_staff_sees_resolved_link(self, user, internal_page):
        md = f"See #{internal_page.slug} for details."
        html = render_markdown(md, viewer=user)
        assert internal_page.title in html
        assert internal_page.get_absolute_url() in html

    def test_anonymous_does_not_see_internal_title(self, internal_page):
        md = f"See #{internal_page.slug} for details."
        html = render_markdown(md, viewer=AnonymousUser())
        assert internal_page.title not in html

    def test_no_viewer_preserves_legacy_behavior(self, internal_page):
        # System/no-request contexts (viewer=None) render unchanged.
        md = f"See #{internal_page.slug} for details."
        html = render_markdown(md)
        assert internal_page.title in html


# --- viewable_pages_q mirrors can_view_page for edge cases --------------


class TestViewableQueryNullDirectory:
    def test_directoryless_inherit_page_is_listed(self, user, db):
        """A directory-less inherit page resolves to the public default in
        can_view_page; viewable_pages_q must include it too."""
        page = Page.objects.create(
            title="Loose",
            slug="loose",
            content="x",
            directory=None,
            owner=user,
            created_by=user,
            updated_by=user,
            visibility=Page.Visibility.INHERIT,
        )
        anon = AnonymousUser()
        assert can_view_page(anon, page) is True
        listed = set(
            Page.objects.filter(viewable_pages_q(anon)).values_list(
                "id", flat=True
            )
        )
        assert page.id in listed
