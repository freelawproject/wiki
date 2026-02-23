import factory
from django.contrib.auth.models import User

from .models import UserProfile


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}@free.law")
    email = factory.LazyAttribute(lambda o: o.username)


class UserProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserProfile

    user = factory.SubFactory(UserFactory)
    display_name = factory.Faker("name")
