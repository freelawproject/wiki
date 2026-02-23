import factory

from wiki.users.factories import UserFactory

from .models import Page, PageRevision


class PageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Page

    title = factory.Sequence(lambda n: f"Test Page {n}")
    slug = factory.Sequence(lambda n: f"test-page-{n}")
    content = factory.Faker("paragraph")
    owner = factory.SubFactory(UserFactory)
    created_by = factory.LazyAttribute(lambda o: o.owner)
    updated_by = factory.LazyAttribute(lambda o: o.owner)
    visibility = Page.Visibility.PUBLIC


class PageRevisionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PageRevision

    page = factory.SubFactory(PageFactory)
    title = factory.LazyAttribute(lambda o: o.page.title)
    content = factory.LazyAttribute(lambda o: o.page.content)
    revision_number = factory.Sequence(lambda n: n + 1)
    created_by = factory.LazyAttribute(lambda o: o.page.owner)
