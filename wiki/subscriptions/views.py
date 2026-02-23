from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from wiki.lib.permissions import can_view_page
from wiki.pages.models import Page

from .models import PageSubscription


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

    sub, created = PageSubscription.objects.get_or_create(
        user=request.user, page=page
    )

    if not created:
        sub.delete()
        subscribed = False
    else:
        subscribed = True

    # HTMX response
    if request.headers.get("HX-Request"):
        label = "Unsubscribe" if subscribed else "Subscribe"
        sub_url = reverse("page_subscribe", kwargs={"path": path})
        return HttpResponse(
            f'<button class="w-full text-left px-4 py-2 text-sm '
            f'hover:bg-gray-100 dark:hover:bg-gray-700" '
            f'hx-post="{sub_url}" '
            f'hx-swap="outerHTML">'
            f"{label}</button>"
        )

    msg = "Subscribed" if subscribed else "Unsubscribed"
    messages.success(request, f"{msg} to {page.title}.")
    return redirect(page.get_absolute_url())


def unsubscribe_landing(request, token):
    """Landing page for email unsubscribe links."""
    from django.core.signing import BadSignature, Signer

    signer = Signer()
    try:
        value = signer.unsign(token)
        user_id, page_id = value.split(":")
    except (BadSignature, ValueError):
        messages.error(request, "Invalid unsubscribe link.")
        return redirect("root")

    if request.method == "POST":
        PageSubscription.objects.filter(
            user_id=user_id, page_id=page_id
        ).delete()
        messages.success(request, "You've been unsubscribed.")
        return redirect("root")

    page = get_object_or_404(Page, id=page_id)
    return render(
        request,
        "subscriptions/unsubscribe.html",
        {"page": page},
    )


@csrf_exempt
@require_POST
def unsubscribe_one_click(request, token):
    """RFC 8058 one-click unsubscribe endpoint.

    Email clients POST directly to this URL — no CSRF token or login
    required. The signed token authenticates the request.
    """
    from django.core.signing import BadSignature, Signer

    signer = Signer()
    try:
        value = signer.unsign(token)
        user_id, page_id = value.split(":")
    except (BadSignature, ValueError):
        return HttpResponse("Invalid token", status=400)

    PageSubscription.objects.filter(user_id=user_id, page_id=page_id).delete()
    return HttpResponse("Unsubscribed", status=200)
