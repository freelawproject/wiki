from django.contrib.auth.models import User
from django.test import TestCase

from wiki.users.models import UserProfile


class WikiTestCase(TestCase):
    """Base test case with helper methods for wiki tests."""

    def make_user(self, email="test@free.law", display_name="Test User"):
        """Create a user with profile."""
        user = User.objects.create_user(
            username=email,
            email=email,
            password="testpass123",
        )
        UserProfile.objects.create(
            user=user,
            display_name=display_name,
        )
        return user

    def login_user(self, user):
        """Log in a user via the test client."""
        self.client.force_login(user)
