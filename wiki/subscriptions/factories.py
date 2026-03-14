import factory

from wiki.directories.factories import DirectoryFactory
from wiki.pages.factories import PageFactory
from wiki.users.factories import UserFactory

from .models import DirectorySubscription, PageSubscription


class PageSubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PageSubscription

    user = factory.SubFactory(UserFactory)
    page = factory.SubFactory(PageFactory)


class DirectorySubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DirectorySubscription

    user = factory.SubFactory(UserFactory)
    directory = factory.SubFactory(DirectoryFactory)
