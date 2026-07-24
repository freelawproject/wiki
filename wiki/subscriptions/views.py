from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import AnonymousUser, User
from django.core.signing import BadSignature, SignatureExpired, Signer
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from wiki.directories.models import Directory
from wiki.lib.page_utils import get_page_from_path
from wiki.lib.permissions import can_view_directory, can_view_page
from wiki.lib.ratelimiter import (
    ratelimit_email_subscribe,
    ratelimit_email_subscribe_daily,
)
from wiki.pages.models import Page

from .forms import EmailSubscribeForm
from .models import (
    DirectorySubscription,
    EmailSubscription,
    PageSubscription,
    SubscriptionStatus,
)
from .tasks import (
    read_confirm_token,
    send_email_subscription_confirmation,
)
from .utils import (
    is_effectively_subscribed_to_directory,
    is_effectively_subscribed_to_page,
    normalize_subscriber_email,
)


@login_required
def toggle_subscription(request, path):
    """Toggle subscription to a page (HTMX or regular POST)."""
    if request.method != "POST":
        raise Http404

    page = get_page_from_path(path)

    if not can_view_page(request.user, page):
        raise Http404

    currently_subscribed = is_effectively_subscribed_to_page(
        request.user, page
    )

    if currently_subscribed:
        PageSubscription.objects.update_or_create(
            user=request.user,
            page=page,
            defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
        )
        subscribed = False
    else:
        PageSubscription.objects.update_or_create(
            user=request.user,
            page=page,
            defaults={"status": SubscriptionStatus.SUBSCRIBED},
        )
        subscribed = True

    # HTMX response
    if request.headers.get("HX-Request"):
        label = "Unsubscribe" if subscribed else "Subscribe"
        flash = "Subscribed!" if subscribed else "Unsubscribed!"
        sub_url = reverse("page_subscribe", kwargs={"path": path})
        return HttpResponse(
            f'<button class="dropdown-item" '
            f'x-data="subscribeToggle" '
            f'data-label="{label}" '
            f'data-flash="{flash}" '
            f'x-text="label" '
            f'hx-post="{sub_url}" '
            f'hx-swap="outerHTML">'
            f"{label}</button>"
        )

    msg = "Subscribed" if subscribed else "Unsubscribed"
    messages.success(request, f"{msg} to {page.title}.")
    return redirect(page.get_absolute_url())


@login_required
def toggle_directory_subscription(request, path=""):
    """Toggle subscription to a directory (HTMX or regular POST)."""
    if request.method != "POST":
        raise Http404

    clean_path = path.strip("/") if path else ""
    directory = get_object_or_404(Directory, path=clean_path)

    if not can_view_directory(request.user, directory):
        raise Http404

    currently_subscribed = is_effectively_subscribed_to_directory(
        request.user, directory
    )

    if currently_subscribed:
        DirectorySubscription.objects.update_or_create(
            user=request.user,
            directory=directory,
            defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
        )
        subscribed = False
    else:
        DirectorySubscription.objects.update_or_create(
            user=request.user,
            directory=directory,
            defaults={"status": SubscriptionStatus.SUBSCRIBED},
        )
        subscribed = True

    # Ajax response
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return HttpResponse(status=204)

    msg = "Subscribed to" if subscribed else "Unsubscribed from"
    messages.success(request, f"{msg} {directory.title}.")
    return redirect(directory.get_absolute_url())


def _unsubscribe_page(request, user_id, page_id):
    """Handle page unsubscribe from email link."""
    if request.method == "POST":
        user = User.objects.filter(id=user_id).first()
        # Use all_objects: delete notifications link here, so the page is
        # often soft-deleted by the time the recipient clicks.
        page = Page.all_objects.filter(id=page_id).first()
        if user and page:
            PageSubscription.objects.update_or_create(
                user=user,
                page=page,
                defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
            )
        messages.success(request, "You've been unsubscribed.")
        return redirect("root")

    page = get_object_or_404(Page.all_objects, id=page_id)
    return render(
        request,
        "subscriptions/unsubscribe.html",
        {"page": page},
    )


def _unsubscribe_directory(request, user_id, directory_id):
    """Handle directory unsubscribe from email link."""
    if request.method == "POST":
        user = User.objects.filter(id=user_id).first()
        directory = Directory.objects.filter(id=directory_id).first()
        if user and directory:
            DirectorySubscription.objects.update_or_create(
                user=user,
                directory=directory,
                defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
            )
        messages.success(request, "You've been unsubscribed.")
        return redirect("root")

    directory = get_object_or_404(Directory, id=directory_id)
    return render(
        request,
        "subscriptions/directory_unsubscribe.html",
        {"directory": directory},
    )


def unsubscribe_landing(request, token):
    """Landing page for email unsubscribe links."""
    signer = Signer()
    try:
        value = signer.unsign(token)
    except BadSignature:
        messages.error(request, "Invalid unsubscribe link.")
        return redirect("root")

    # Directory token format: "d:{user_id}:{directory_id}"
    if value.startswith("d:"):
        try:
            _, user_id, directory_id = value.split(":")
        except ValueError:
            messages.error(request, "Invalid unsubscribe link.")
            return redirect("root")
        return _unsubscribe_directory(request, user_id, directory_id)

    # Anonymous email token format: "e:{email_subscription_id}"
    if value.startswith("e:"):
        try:
            _, sub_id = value.split(":")
        except ValueError:
            messages.error(request, "Invalid unsubscribe link.")
            return redirect("root")
        return _unsubscribe_email(request, sub_id)

    # Page token format: "{user_id}:{page_id}"
    try:
        user_id, page_id = value.split(":")
    except ValueError:
        messages.error(request, "Invalid unsubscribe link.")
        return redirect("root")
    return _unsubscribe_page(request, user_id, page_id)


def _unsubscribe_email(request, sub_id):
    """Confirm-then-delete for anonymous email subscriptions.

    Tokens carry the row id, so deletion is naturally idempotent: a
    re-clicked link finds no row and still reports success.
    """
    sub = (
        EmailSubscription.objects.filter(id=sub_id)
        .select_related("page")
        .first()
    )
    if request.method == "POST":
        if sub:
            sub.delete()
        messages.success(request, "You've been unsubscribed.")
        return redirect("root")
    return render(
        request, "subscriptions/email_unsubscribe.html", {"sub": sub}
    )


@csrf_exempt
@require_POST
def unsubscribe_one_click(request, token):
    """RFC 8058 one-click unsubscribe endpoint.

    Email clients POST directly to this URL — no CSRF token or login
    required. The signed token authenticates the request.
    """
    signer = Signer()
    try:
        value = signer.unsign(token)
    except BadSignature:
        return HttpResponse("Invalid token", status=400)

    # Directory token format: "d:{user_id}:{directory_id}"
    if value.startswith("d:"):
        try:
            _, user_id, directory_id = value.split(":")
        except ValueError:
            return HttpResponse("Invalid token", status=400)
        user = User.objects.filter(id=user_id).first()
        directory = Directory.objects.filter(id=directory_id).first()
        if user and directory:
            DirectorySubscription.objects.update_or_create(
                user=user,
                directory=directory,
                defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
            )
        return HttpResponse("Unsubscribed", status=200)

    # Anonymous email token format: "e:{email_subscription_id}"
    if value.startswith("e:"):
        try:
            _, sub_id = value.split(":")
        except ValueError:
            return HttpResponse("Invalid token", status=400)
        EmailSubscription.objects.filter(id=sub_id).delete()
        return HttpResponse("Unsubscribed", status=200)

    # Page token format: "{user_id}:{page_id}"
    try:
        user_id, page_id = value.split(":")
    except ValueError:
        return HttpResponse("Invalid token", status=400)

    user = User.objects.filter(id=user_id).first()
    # Use all_objects: delete notifications link here, so the page is
    # often soft-deleted by the time the recipient clicks.
    page = Page.all_objects.filter(id=page_id).first()
    if user and page:
        PageSubscription.objects.update_or_create(
            user=user,
            page=page,
            defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
        )

    return HttpResponse("Unsubscribed", status=200)


def _email_subscribable_page_or_404(path):
    """Resolve a page that accepts anonymous email subscriptions.

    Requires public history AND anonymous viewability — gate on
    AnonymousUser, not the requester: a logged-in user must not be able
    to wire an outside address to a page the public can't read.
    Unavailable == missing (probe-resistant 404).
    """
    page = get_page_from_path(path)
    if not page.history_is_public or not can_view_page(AnonymousUser(), page):
        raise Http404
    return page


@never_cache
@ratelimit_email_subscribe
@ratelimit_email_subscribe_daily
def email_subscribe(request, path):
    """Dedicated (non-cached) subscribe page: GET form, POST confirms.

    The POST stores nothing — it only emails a signed confirmation
    link. New, duplicate, and honeypotted submissions all render the
    same neutral "check your email" page so nothing can be enumerated.
    """
    page = _email_subscribable_page_or_404(path)
    if request.method == "POST":
        form = EmailSubscribeForm(request.POST)
        if form.is_valid() and not form.is_spam:
            send_email_subscription_confirmation(
                page, form.cleaned_data["email"]
            )
        if form.is_valid() or form.is_spam:
            return render(
                request,
                "subscriptions/email_subscribe_sent.html",
                {"page": page},
            )
    else:
        form = EmailSubscribeForm()
    return render(
        request,
        "subscriptions/email_subscribe.html",
        {"page": page, "form": form},
    )


@never_cache
def email_subscribe_confirm(request, token):
    """Landing for the emailed confirmation link.

    GET shows a confirm button; only the POST creates the subscription,
    so mail-scanner link prefetches can't confirm on the user's behalf.
    """
    try:
        payload = read_confirm_token(token)
    except SignatureExpired:
        # Subclass of BadSignature — must be caught first.
        return render(
            request, "subscriptions/email_subscribe_expired.html", status=400
        )
    except BadSignature:
        return render(
            request, "subscriptions/email_subscribe_invalid.html", status=400
        )

    page = Page.objects.filter(id=payload["p"]).first()
    if (
        page is None
        or not page.history_is_public
        or not can_view_page(AnonymousUser(), page)
    ):
        # Deleted / toggled off / made private since the email was sent.
        return render(
            request,
            "subscriptions/email_subscribe_unavailable.html",
            status=404,
        )

    if request.method == "POST":
        # get_or_create: re-clicking an already-used link is a no-op.
        EmailSubscription.objects.get_or_create(
            page=page, email=normalize_subscriber_email(payload["e"])
        )
        return render(
            request,
            "subscriptions/email_subscribe_confirmed.html",
            {"page": page},
        )
    return render(
        request,
        "subscriptions/email_subscribe_confirm.html",
        {"page": page, "token": token},
    )
