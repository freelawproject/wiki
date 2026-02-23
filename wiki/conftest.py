"""Shared pytest fixtures for the wiki project."""

import pytest
from django.contrib.auth.models import Group, User

from wiki.directories.models import Directory
from wiki.pages.models import Page, PageRevision
from wiki.users.models import SystemConfig, UserProfile


@pytest.fixture
def user(db):
    """A regular @free.law user with profile."""
    u = User.objects.create_user(
        username="alice@free.law",
        email="alice@free.law",
        password="testpass",
    )
    UserProfile.objects.create(
        user=u,
        display_name="Alice",
        gravatar_url=UserProfile.gravatar_url_for_email(u.email),
    )
    return u


@pytest.fixture
def other_user(db):
    """A second user for permission/subscription tests."""
    u = User.objects.create_user(
        username="bob@free.law",
        email="bob@free.law",
        password="testpass",
    )
    UserProfile.objects.create(user=u, display_name="Bob")
    return u


@pytest.fixture
def owner_user(user):
    """Make 'user' the system owner."""
    SystemConfig.objects.create(owner=user)
    return user


@pytest.fixture
def root_directory(db):
    """Root directory (path='')."""
    return Directory.objects.create(path="", title="Home")


@pytest.fixture
def sub_directory(root_directory, user):
    """A child directory under root."""
    return Directory.objects.create(
        path="engineering",
        title="Engineering",
        parent=root_directory,
        owner=user,
        created_by=user,
    )


@pytest.fixture
def nested_directory(sub_directory, user):
    """A grandchild directory: engineering/devops."""
    return Directory.objects.create(
        path="engineering/devops",
        title="DevOps",
        parent=sub_directory,
        owner=user,
        created_by=user,
    )


@pytest.fixture
def private_directory(root_directory, user):
    """A private child directory under root."""
    return Directory.objects.create(
        path="secret-team",
        title="Secret Team",
        parent=root_directory,
        owner=user,
        created_by=user,
        visibility=Directory.Visibility.PRIVATE,
    )


@pytest.fixture
def page(user):
    """A public page with one revision."""
    p = Page.objects.create(
        title="Getting Started",
        slug="getting-started",
        content="## Welcome\n\nHello world.",
        owner=user,
        created_by=user,
        updated_by=user,
        visibility=Page.Visibility.PUBLIC,
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


@pytest.fixture
def private_page(user):
    """A private page visible only to owner."""
    p = Page.objects.create(
        title="Secret Notes",
        slug="secret-notes",
        content="Top secret.",
        owner=user,
        created_by=user,
        updated_by=user,
        visibility=Page.Visibility.PRIVATE,
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


@pytest.fixture
def page_in_directory(user, sub_directory):
    """A page inside the engineering directory."""
    p = Page.objects.create(
        title="Coding Standards",
        slug="coding-standards",
        content="Use ruff.",
        directory=sub_directory,
        owner=user,
        created_by=user,
        updated_by=user,
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


@pytest.fixture
def group(db):
    """A test group."""
    return Group.objects.create(name="Engineering Team")
