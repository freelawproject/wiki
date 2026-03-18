from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.signing import BadSignature, Signer
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from wiki.directories.models import Directory
from wiki.lib.permissions import can_view_directory, can_view_page
from wiki.pages.models import Page

from .models import (
    DirectorySubscription,
    PageSubscription,
    SubscriptionStatus,
)
from .utils import (
    is_effectively_subscribed_to_directory,
    is_effectively_subscribed_to_page,
)


@login_required
def toggle_subscription(request, path):
    """Toggle subscription to a page (HTMX or regular POST)."""
    if request.method != "POST":
        raise Http404

    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

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
        page = Page.objects.filter(id=page_id).first()
        if user and page:
            PageSubscription.objects.update_or_create(
                user=user,
                page=page,
                defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
            )
        messages.success(request, "You've been unsubscribed.")
        return redirect("root")

    page = get_object_or_404(Page, id=page_id)
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

    # Page token format: "{user_id}:{page_id}"
    try:
        user_id, page_id = value.split(":")
    except ValueError:
        messages.error(request, "Invalid unsubscribe link.")
        return redirect("root")
    return _unsubscribe_page(request, user_id, page_id)


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

    # Page token format: "{user_id}:{page_id}"
    try:
        user_id, page_id = value.split(":")
    except ValueError:
        return HttpResponse("Invalid token", status=400)

    user = User.objects.filter(id=user_id).first()
    page = Page.objects.filter(id=page_id).first()
    if user and page:
        PageSubscription.objects.update_or_create(
            user=user,
            page=page,
            defaults={"status": SubscriptionStatus.UNSUBSCRIBED},
        )

    return HttpResponse("Unsubscribed", status=200)
