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
from wiki.lib.permissions import can_view_page
from wiki.pages.models import Page

from .models import (
    DirectorySubscription,
    PageSubscription,
    SubscriptionExclusion,
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
        # Unsubscribe: delete direct subscription
        PageSubscription.objects.filter(user=request.user, page=page).delete()
        # If still covered by a directory subscription, create an exclusion
        if is_effectively_subscribed_to_page(request.user, page):
            SubscriptionExclusion.objects.get_or_create(
                user=request.user, page=page
            )
        subscribed = False
    else:
        # Subscribe: create direct subscription and remove any exclusion
        PageSubscription.objects.get_or_create(user=request.user, page=page)
        SubscriptionExclusion.objects.filter(
            user=request.user, page=page
        ).delete()
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

    currently_subscribed = is_effectively_subscribed_to_directory(
        request.user, directory
    )

    if currently_subscribed:
        # Unsubscribe: delete direct subscription
        DirectorySubscription.objects.filter(
            user=request.user, directory=directory
        ).delete()
        # If still covered by a parent directory subscription, create exclusion
        if is_effectively_subscribed_to_directory(request.user, directory):
            SubscriptionExclusion.objects.get_or_create(
                user=request.user, directory=directory
            )
        subscribed = False
    else:
        # Subscribe: create subscription and remove any exclusion
        DirectorySubscription.objects.get_or_create(
            user=request.user, directory=directory
        )
        SubscriptionExclusion.objects.filter(
            user=request.user, directory=directory
        ).delete()
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
        PageSubscription.objects.filter(
            user_id=user_id, page_id=page_id
        ).delete()
        # If still covered by directory subscription, create exclusion
        page = Page.objects.filter(id=page_id).first()
        user = User.objects.filter(id=user_id).first()
        if page and user and is_effectively_subscribed_to_page(user, page):
            SubscriptionExclusion.objects.get_or_create(user=user, page=page)
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
        DirectorySubscription.objects.filter(
            user_id=user_id, directory_id=directory_id
        ).delete()
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
        DirectorySubscription.objects.filter(
            user_id=user_id, directory_id=directory_id
        ).delete()
        return HttpResponse("Unsubscribed", status=200)

    # Page token format: "{user_id}:{page_id}"
    try:
        user_id, page_id = value.split(":")
    except ValueError:
        return HttpResponse("Invalid token", status=400)

    # Delete direct subscription
    PageSubscription.objects.filter(user_id=user_id, page_id=page_id).delete()
    # If still covered by directory subscription, create exclusion
    page = Page.objects.filter(id=page_id).first()
    user = User.objects.filter(id=user_id).first()
    if page and user and is_effectively_subscribed_to_page(user, page):
        SubscriptionExclusion.objects.get_or_create(user=user, page=page)

    return HttpResponse("Unsubscribed", status=200)
