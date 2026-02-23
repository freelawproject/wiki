import factory

from wiki.pages.factories import PageFactory
from wiki.users.factories import UserFactory

from .models import PageSubscription


class PageSubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PageSubscription

    user = factory.SubFactory(UserFactory)
    page = factory.SubFactory(PageFactory)
