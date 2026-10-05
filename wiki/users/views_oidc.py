from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from mozilla_django_oidc.views import (
    OIDCAuthenticationCallbackView,
    OIDCAuthenticationRequestView,
)

from wiki.lib.ratelimiter import ratelimit_oidc


class CourtListenerLoginEnabledMixin:
    """404 the CourtListener sign-in routes until a client is configured."""

    def dispatch(self, request, *args, **kwargs):
        if not settings.COURTLISTENER_LOGIN_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


@method_decorator(ratelimit_oidc, name="dispatch")
class CourtListenerLoginView(
    CourtListenerLoginEnabledMixin, OIDCAuthenticationRequestView
):
    """Send the user to CourtListener to authorize the wiki."""


@method_decorator(ratelimit_oidc, name="dispatch")
class CourtListenerCallbackView(
    CourtListenerLoginEnabledMixin, OIDCAuthenticationCallbackView
):
    """Finish the code exchange and sign the user in."""

    def login_failure(self):
        messages.error(
            self.request,
            "We couldn't sign you in with CourtListener. Your CourtListener "
            "email must be confirmed and allowed to sign in here.",
        )
        return redirect("login")

    def login_success(self):
        messages.success(self.request, "You're now signed in.")
        return super().login_success()
