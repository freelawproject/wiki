import secrets

from django.contrib import messages
from django.contrib.auth import SESSION_KEY, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from wiki.lib.permissions import is_system_owner
from wiki.users.forms import LoginForm, UserSettingsForm
from wiki.users.models import SystemConfig, UserProfile
from wiki.users.tasks import send_magic_link_email


def login_view(request):
    """Show login form and send magic link email."""
    if request.user.is_authenticated:
        return redirect("root")

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]

        # Get or create user (look up by username, which is unique)
        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email},
        )

        if not user.is_active:
            messages.error(
                request,
                "Your account has been archived. "
                "Contact an admin to restore access.",
            )
            return redirect("login")

        # Get or create profile
        profile, profile_created = UserProfile.objects.get_or_create(user=user)
        if profile_created:
            profile.gravatar_url = UserProfile.gravatar_url_for_email(email)

        # First user to log in becomes system owner and admin
        if not SystemConfig.objects.exists():
            SystemConfig.objects.create(owner=user)
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])

        # Generate magic link token
        raw_token = secrets.token_urlsafe(32)
        profile.set_magic_token(raw_token)
        profile.save()

        send_magic_link_email(email, raw_token)

        messages.success(
            request,
            "Check your email for a sign-in link. It expires in 15 minutes.",
        )
        return redirect("login")

    return render(request, "users/login.html", {"form": form})


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

    if profile.verify_magic_token(token):
        profile.clear_magic_token()
        profile.save()
        login(
            request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        messages.success(request, "You're now signed in.")
        return redirect("root")
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
        # Archive: deactivate and delete all sessions
        target.is_active = False
        target.save(update_fields=["is_active"])
        for session in Session.objects.filter(expire_date__gt=timezone.now()):
            if session.get_decoded().get(SESSION_KEY) == str(target.pk):
                session.delete()
        messages.success(request, f"{target.email} has been archived.")
    else:
        # Unarchive: reactivate
        target.is_active = True
        target.save(update_fields=["is_active"])
        messages.success(request, f"{target.email} has been unarchived.")

    return redirect("admin_list")


@login_required
def user_search_htmx(request):
    """JSON endpoint for user @-mention autocomplete.

    Returns list of {username, display_name, gravatar_url} objects.
    """
    q = request.GET.get("q", "").strip()
    if len(q) < 1:
        return JsonResponse([], safe=False)

    users = (
        User.objects.filter(email__istartswith=q)
        .exclude(pk=request.user.pk)
        .select_related("profile")[:10]
    )

    results = []
    for u in users:
        name = u.email.split("@")[0]
        display = name
        gravatar = ""
        if hasattr(u, "profile"):
            display = u.profile.display_name or name
            gravatar = u.profile.gravatar_url or ""
        results.append(
            {
                "username": name,
                "display_name": display,
                "gravatar_url": gravatar,
            }
        )

    return JsonResponse(results, safe=False)
