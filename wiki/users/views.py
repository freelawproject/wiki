import secrets
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control

from wiki.lib.access import is_email_allowed, is_internal_user
from wiki.lib.favicons import store_favicon
from wiki.lib.permissions import (
    is_system_owner,
    mark_domain_grants_dormant,
    reactivate_domain_grants,
)
from wiki.lib.ratelimiter import ratelimit_login
from wiki.lib.sessions import end_sessions_for_users, revoke_disallowed
from wiki.lib.users import provision_user
from wiki.users.forms import (
    AllowedDomainForm,
    AllowedEmailForm,
    LoginForm,
    UserSettingsForm,
)
from wiki.users.models import (
    AllowedDomain,
    AllowedEmail,
    SystemConfig,
    UserProfile,
)
from wiki.users.tasks import (
    notify_access_change,
    notify_email_access_granted,
    send_magic_link_email,
)


def _safe_next_url(request, url):
    """Return ``url`` if it's a safe same-host redirect target, else "".

    The leading-slash check keeps bare strings (e.g. "admin_list") out of
    ``redirect()``, which would otherwise reverse() them as pattern names.
    """
    if (
        url
        and url.startswith("/")
        and url_has_allowed_host_and_scheme(
            url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return url
    return ""


# SECURITY: rate limit login POSTs to prevent magic link email spam.
@ratelimit_login
def login_view(request):
    """Show login form and send magic link email."""
    next_url = _safe_next_url(
        request, request.POST.get("next") or request.GET.get("next")
    )
    if request.user.is_authenticated:
        return redirect(next_url or "root")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]

        # Only mint an account and send a link for an allowed, active address.
        # The response is identical in every case (below) so the form never
        # reveals whether an address is on the allowlist or has been archived.
        if is_email_allowed(email):
            user = provision_user(email)
            if user is not None:
                profile = user.profile

                # First user to log in becomes system owner and admin.
                if not SystemConfig.objects.exists():
                    SystemConfig.objects.create(owner=user)
                    user.is_staff = True
                    user.is_superuser = True
                    user.save(update_fields=["is_staff", "is_superuser"])

                # Generate magic link token and send the email.
                raw_token = secrets.token_urlsafe(32)
                profile.set_magic_token(raw_token)
                profile.save()
                send_magic_link_email(email, raw_token, next_url=next_url)

        messages.success(
            request,
            "If that address is allowed to sign in, we've emailed a "
            "sign-in link. It expires in 15 minutes.",
        )
        # Keep ?next= on the post-submit page so a retry (e.g. after a
        # typo'd address) still lands the user on their original page.
        login_url = reverse("login")
        if next_url:
            login_url += "?" + urlencode({"next": next_url})
        return redirect(login_url)

    return render(
        request, "users/login.html", {"form": form, "next_url": next_url}
    )


def verify_view(request):
    """Verify a magic link token and log the user in."""
    token = request.GET.get("token", "")
    email = request.GET.get("email", "")

    if not token or not email:
        messages.error(request, "Invalid sign-in link.")
        return redirect("login")

    try:
        user = User.objects.get(username=email)
        profile = user.profile
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        messages.error(request, "Invalid sign-in link.")
        return redirect("login")

    if not user.is_active:
        messages.error(
            request,
            "Your account has been archived. "
            "Contact an admin to restore access.",
        )
        return redirect("login")

    # An outstanding magic link is a bearer credential: re-check the
    # allowlist at redemption so a link minted before the user's domain or
    # address was removed can't still mint a session. Kill the token too.
    if not is_email_allowed(user.email):
        profile.clear_magic_token()
        profile.save()
        messages.error(
            request,
            "Your sign-in access has been revoked. Contact an admin.",
        )
        return redirect("login")

    if profile.verify_magic_token(token):
        profile.clear_magic_token()
        profile.save()
        login(
            request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        messages.success(request, "You're now signed in.")
        # The link's next param is attacker-influenced (anyone can compose
        # a verify URL), so only follow it to a same-host destination.
        next_url = _safe_next_url(request, request.GET.get("next"))
        return redirect(next_url or "root")
    else:
        messages.error(request, "This sign-in link has expired or is invalid.")
        return redirect("login")


def logout_view(request):
    """Log the user out."""
    if request.method == "POST":
        logout(request)
        messages.info(request, "You've been signed out.")
    return redirect("root")


@login_required
def settings_view(request):
    """User settings page (display name)."""
    profile = request.user.profile

    if request.method == "POST":
        form = UserSettingsForm(request.POST)
        if form.is_valid():
            profile.display_name = form.cleaned_data["display_name"]
            profile.save()
            messages.success(request, "Settings updated.")
            return redirect("user_settings")
    else:
        form = UserSettingsForm(initial={"display_name": profile.display_name})

    return render(request, "users/settings.html", {"form": form})


@login_required
def admin_list(request):
    """List all users with admin status. Staff/system-owner only."""
    if not request.user.is_staff and not is_system_owner(request.user):
        raise Http404

    users = User.objects.all().select_related("profile").order_by("email")

    # Get system owner for display
    system_owner = None
    try:
        config = SystemConfig.objects.get(pk=1)
        system_owner = config.owner
    except SystemConfig.DoesNotExist:
        pass

    return render(
        request,
        "users/admin_list.html",
        {
            "users": users,
            "system_owner": system_owner,
        },
    )


@login_required
def admin_toggle(request, pk):
    """Toggle a user's admin (staff/superuser) status."""
    if not request.user.is_staff and not is_system_owner(request.user):
        raise Http404

    if request.method != "POST":
        return redirect("admin_list")

    target = User.objects.filter(pk=pk).first()
    if not target:
        messages.error(request, "User not found.")
        return redirect("admin_list")

    # Cannot de-admin the system owner
    try:
        config = SystemConfig.objects.get(pk=1)
        if target.id == config.owner_id and target.is_staff:
            messages.error(
                request,
                "Cannot remove admin from the system owner.",
            )
            return redirect("admin_list")
    except SystemConfig.DoesNotExist:
        pass

    target.is_staff = not target.is_staff
    target.is_superuser = target.is_staff
    target.save(update_fields=["is_staff", "is_superuser"])

    action = "promoted to" if target.is_staff else "removed from"
    messages.success(
        request,
        f"{target.email} {action} admin.",
    )
    return redirect("admin_list")


@login_required
def admin_archive_toggle(request, pk):
    """Toggle a user's archived (is_active) status."""
    if not request.user.is_staff and not is_system_owner(request.user):
        raise Http404

    if request.method != "POST":
        return redirect("admin_list")

    target = User.objects.filter(pk=pk).first()
    if not target:
        messages.error(request, "User not found.")
        return redirect("admin_list")

    # Cannot archive the system owner
    try:
        config = SystemConfig.objects.get(pk=1)
        if target.id == config.owner_id:
            messages.error(request, "Cannot archive the system owner.")
            return redirect("admin_list")
    except SystemConfig.DoesNotExist:
        pass

    if target.is_active:
        # Archive: deactivate, end sessions, and kill any outstanding magic
        # link so it can't be redeemed (e.g. after a quick un-archive).
        with transaction.atomic():
            target.is_active = False
            target.save(update_fields=["is_active"])
            end_sessions_for_users([target.pk])
            if hasattr(target, "profile"):
                target.profile.clear_magic_token()
                target.profile.save(
                    update_fields=["magic_link_token", "magic_link_expires"]
                )
        messages.success(request, f"{target.email} has been archived.")
    else:
        # Unarchive: reactivate
        target.is_active = True
        target.save(update_fields=["is_active"])
        messages.success(request, f"{target.email} has been unarchived.")

    return redirect("admin_list")


def _can_manage_admin(user):
    """Staff or system owner may manage admin settings."""
    return user.is_staff or is_system_owner(user)


def _announce_access_change(request, action, item_type, value, tier=None):
    """Notify the owner and managers of a change and confirm to the actor.

    Email sending is a side effect kept outside any transaction.
    """
    recipients = notify_access_change(
        request.user, action, item_type, value, tier=tier
    )
    if recipients:
        messages.info(
            request, "The owner and managers have been notified by email."
        )


def _form_error_message(form):
    """Flatten a form's errors into one readable string.

    Covers errors on any field (e.g. a too-long note) instead of only the
    primary field, so the user isn't told "Invalid domain" for a valid
    domain with a bad note.
    """
    flat = "; ".join(err for errs in form.errors.values() for err in errs)
    return flat or "Invalid input."


@login_required
def access_list(request):
    """Manage the sign-in allowlist (domains + individual emails)."""
    if not _can_manage_admin(request.user):
        raise Http404

    return render(
        request,
        "users/access_list.html",
        {
            "domains": AllowedDomain.objects.all(),
            "emails": AllowedEmail.objects.all(),
            "domain_form": AllowedDomainForm(auto_id="id_domain_%s"),
            "email_form": AllowedEmailForm(auto_id="id_email_%s"),
            "is_owner": is_system_owner(request.user),
        },
    )


@login_required
def access_add_domain(request):
    """Add an allowed email domain. Owner only."""
    if not _can_manage_admin(request.user):
        raise Http404
    if not is_system_owner(request.user):
        messages.error(
            request, "Only the system owner can add or remove domains."
        )
        return redirect("access_list")
    if request.method != "POST":
        return redirect("access_list")

    form = AllowedDomainForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("access_list")

    domain = form.cleaned_data["domain"]
    obj, created = AllowedDomain.objects.get_or_create(
        domain=domain,
        defaults={
            "suffix": form.cleaned_data["suffix"],
            "note": form.cleaned_data["note"],
            "tier": form.cleaned_data["tier"],
        },
    )
    if not created:
        messages.info(request, f"Domain {domain} was already allowed.")
        return redirect("access_list")

    # Reactivate any content grants retained from a previous stint on the
    # allowlist so re-adding a domain restores its exact prior access.
    reactivate_domain_grants(domain)
    # Best-effort: grab the favicon now so the access badge has it; the daemon
    # backfills/retries if this fails (e.g. the fetch times out).
    store_favicon(obj)
    messages.success(request, f"Domain {domain} is now allowed.")
    _announce_access_change(
        request, "added", "domain", domain, tier=form.cleaned_data["tier"]
    )
    return redirect("access_list")


@login_required
def access_add_email(request):
    """Add a single allowed email address. Owner or managers."""
    if not _can_manage_admin(request.user):
        raise Http404
    if request.method != "POST":
        return redirect("access_list")

    form = AllowedEmailForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_error_message(form))
        return redirect("access_list")

    email = form.cleaned_data["email"]
    _, created = AllowedEmail.objects.get_or_create(
        email=email,
        defaults={
            "note": form.cleaned_data["note"],
            "tier": form.cleaned_data["tier"],
        },
    )
    if not created:
        messages.info(request, f"{email} was already allowed.")
        return redirect("access_list")

    # Tell the person they can now sign in.
    notify_email_access_granted(email)
    messages.success(request, f"{email} is now allowed.")
    _announce_access_change(
        request,
        "added",
        "email address",
        email,
        tier=form.cleaned_data["tier"],
    )
    return redirect("access_list")


@cache_control(private=True, max_age=86400)
def domain_favicon(request, domain):
    """Serve a granting domain's stored favicon as a PNG.

    Staff-only: the access badge only renders for staff, and gating the
    endpoint keeps it from being an open allowlist-enumeration oracle.
    Returns 404 (same as a missing domain) when no favicon is stored, so the
    template falls back to the generic icon.
    """
    if not is_internal_user(request.user):
        raise Http404
    obj = AllowedDomain.objects.filter(domain=domain).first()
    if obj is None or not obj.favicon_data:
        raise Http404
    return HttpResponse(bytes(obj.favicon_data), content_type="image/png")


@login_required
def access_delete_domain(request, pk):
    """Remove an allowed domain. Owner only."""
    if not _can_manage_admin(request.user):
        raise Http404
    if not is_system_owner(request.user):
        messages.error(
            request, "Only the system owner can add or remove domains."
        )
        return redirect("access_list")
    if request.method != "POST":
        return redirect("access_list")

    domain = AllowedDomain.objects.filter(pk=pk).first()
    if domain:
        value = domain.domain
        domain.delete()
        revoke_disallowed(User.objects.filter(email__iendswith=f"@{value}"))
        # Keep the domain's content grants but flag them dormant so the
        # cleanup job can expire them if the domain stays gone.
        mark_domain_grants_dormant(value)
        messages.success(request, f"Domain {value} removed.")
        _announce_access_change(request, "removed", "domain", value)
    return redirect("access_list")


@login_required
def access_delete_email(request, pk):
    """Remove an allowed email address. Owner or managers."""
    if not _can_manage_admin(request.user):
        raise Http404
    if request.method != "POST":
        return redirect("access_list")

    email = AllowedEmail.objects.filter(pk=pk).first()
    if email:
        value = email.email
        email.delete()
        revoke_disallowed(User.objects.filter(email__iexact=value))
        messages.success(request, f"{value} removed.")
        _announce_access_change(request, "removed", "email address", value)
    return redirect("access_list")


@login_required
def user_search_htmx(request):
    """JSON endpoint for user @-mention autocomplete.

    Returns list of {username, display_name, gravatar_url} objects.
    """
    q = request.GET.get("q", "").strip()
    if len(q) < 1:
        return JsonResponse([], safe=False)

    # Match the typed @-handle (or a display name). The inner join on
    # profile means every result has a handle. The requesting user is
    # excluded by default (you don't @-mention yourself), but callers like
    # the group member form pass include_self=1 since adding yourself to a
    # group is legitimate (see issue #130).
    users = User.objects.filter(
        Q(profile__handle__istartswith=q)
        | Q(profile__display_name__icontains=q)
    )
    if request.GET.get("include_self") != "1":
        users = users.exclude(pk=request.user.pk)
    users = users.select_related("profile")[:10]

    results = []
    for u in users:
        handle = u.profile.handle or u.email.split("@")[0]
        results.append(
            {
                "username": handle,
                "display_name": u.profile.display_name or handle,
                "gravatar_url": u.profile.gravatar_url or "",
            }
        )

    return JsonResponse(results, safe=False)
