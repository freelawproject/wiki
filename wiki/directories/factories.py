import factory

from wiki.users.factories import UserFactory

from .models import Directory


class DirectoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Directory

    title = factory.Sequence(lambda n: f"Directory {n}")
    path = factory.Sequence(lambda n: f"dir-{n}")
    owner = factory.SubFactory(UserFactory)
    created_by = factory.LazyAttribute(lambda o: o.owner)
