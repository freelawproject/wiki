import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from wiki.lib.edit_lock import (
    acquire_lock_for_page,
    get_active_lock_for_page,
    release_lock_for_page,
)
from wiki.lib.markdown import render_markdown
from wiki.lib.permissions import (
    can_edit_directory,
    can_edit_page,
    can_view_page,
    is_editability_more_open_than_visibility,
    is_more_open_than,
)

from .forms import PageForm
from .models import (
    FileUpload,
    Page,
    PagePermission,
    PageRevision,
    PageViewTally,
    SlugRedirect,
)

# Matches @username (word chars only, not followed by @)
_MENTION_RE = __import__("re").compile(r"@([a-zA-Z][a-zA-Z0-9._-]*)")


def _extract_mentions(text):
    """Extract @mention usernames from text."""
    return list(set(_MENTION_RE.findall(text or "")))


def _collect_grant_access(post_data):
    """Collect per-user access grants from POST data.

    Expects fields like grant_access_<username>=view|edit.
    Returns dict mapping {username: "view"|"edit"}.
    """
    grants = {}
    prefix = "grant_access_"
    for key in post_data:
        if key.startswith(prefix):
            username = key[len(prefix) :]
            level = post_data[key]
            if level in ("view", "edit"):
                grants[username] = level
    return grants


def _resolve_or_create_directory(dir_path, user):
    """Resolve a directory path, creating missing segments as needed."""
    from wiki.directories.models import Directory

    directory = Directory.objects.filter(path=dir_path).first()
    if directory:
        return directory

    # Build each segment of the path, creating as needed
    segments = dir_path.strip("/").split("/")
    parent, _ = Directory.objects.get_or_create(
        path="", defaults={"title": "Home"}
    )
    current_path = ""

    for segment in segments:
        current_path = f"{current_path}/{segment}" if current_path else segment
        directory, created = Directory.objects.get_or_create(
            path=current_path,
            defaults={
                "title": segment.replace("-", " ").title(),
                "parent": parent,
                "owner": user,
                "created_by": user,
            },
        )
        parent = directory

    return directory


def resolve_path(request, path):
    """Unified catch-all: resolve a path as directory or page.

    1. Check if path matches a Directory → directory view
    2. Take last segment as slug, check Page → page view
    3. Check SlugRedirect → redirect
    4. 404
    """
    from wiki.directories.models import Directory
    from wiki.directories.views import directory_detail

    clean_path = path.strip("/")

    # 1. Is it a directory?
    if Directory.objects.filter(path=clean_path).exists():
        return directory_detail(request, path)

    # 2. Try as a page (last segment = slug)
    segments = clean_path.split("/")
    slug = segments[-1]

    page = (
        Page.objects.filter(slug=slug)
        .select_related("directory", "owner")
        .first()
    )

    # 3. Check slug redirects
    if page is None:
        redirect_obj = (
            SlugRedirect.objects.filter(old_slug=slug)
            .select_related("page")
            .first()
        )
        if redirect_obj:
            return redirect(redirect_obj.page.get_absolute_url())
        raise Http404

    return _render_page_detail(request, page)


def page_detail(request, path):
    """Display a wiki page. Handles slug redirects and view counting."""
    segments = path.strip("/").split("/")
    slug = segments[-1]

    page = (
        Page.objects.filter(slug=slug)
        .select_related("directory", "owner")
        .first()
    )

    if page is None:
        redirect_obj = (
            SlugRedirect.objects.filter(old_slug=slug)
            .select_related("page")
            .first()
        )
        if redirect_obj:
            return redirect(redirect_obj.page.get_absolute_url())
        raise Http404

    return _render_page_detail(request, page)


def _get_page_people(page):
    """Collect creator, admins, and editors for a page.

    Returns a dict with 'creator', 'admins', and 'editors' — each a list
    of User objects. Admins are not duplicated in editors.
    """
    from django.contrib.auth.models import User

    from wiki.directories.models import DirectoryPermission

    creator = page.created_by
    admin_ids = set()
    editor_ids = set()

    # Owner is always an admin
    if page.owner_id:
        admin_ids.add(page.owner_id)

    # Page-level permissions
    for perm in page.permissions.filter(user__isnull=False).select_related(
        "user"
    ):
        if perm.permission_type == PagePermission.PermissionType.OWNER:
            admin_ids.add(perm.user_id)
        elif perm.permission_type == PagePermission.PermissionType.EDIT:
            editor_ids.add(perm.user_id)

    # Walk directory ancestry for inherited permissions
    directory = page.directory
    while directory is not None:
        for perm in directory.permissions.filter(
            user__isnull=False
        ).select_related("user"):
            if perm.permission_type in (
                DirectoryPermission.PermissionType.OWNER,
                DirectoryPermission.PermissionType.EDIT,
            ):
                editor_ids.add(perm.user_id)
        directory = directory.parent

    # Remove admins from editors to avoid duplication
    editor_ids -= admin_ids
    # Remove creator from both (shown separately)
    if creator:
        admin_ids.discard(creator.id)
        editor_ids.discard(creator.id)

    admins = (
        User.objects.filter(id__in=admin_ids)
        .select_related("profile")
        .order_by("email")
        if admin_ids
        else []
    )
    editors = (
        User.objects.filter(id__in=editor_ids)
        .select_related("profile")
        .order_by("email")
        if editor_ids
        else []
    )

    return {
        "creator": creator,
        "admins": list(admins),
        "editors": list(editors),
    }


def _render_page_detail(request, page):
    """Render the page detail view (shared by resolve_path and page_detail)."""
    if not can_view_page(request.user, page):
        raise Http404

    # Record page view tally
    PageViewTally.objects.create(page=page)

    rendered_content = render_markdown(page.content)
    toc = getattr(rendered_content, "toc_html", "")

    # Build breadcrumbs
    breadcrumbs = [("Home", reverse("root"))]
    if page.directory:
        for ancestor in page.directory.get_ancestors():
            if not ancestor.path:
                continue  # skip root — already in breadcrumbs
            breadcrumbs.append((ancestor.title, ancestor.get_absolute_url()))
        breadcrumbs.append(
            (page.directory.title, page.directory.get_absolute_url())
        )
    breadcrumbs.append((page.title, page.get_absolute_url()))

    # Check subscription status and get subscriber list
    is_subscribed = False
    subscribers = []
    if request.user.is_authenticated:
        from wiki.subscriptions.models import PageSubscription

        is_subscribed = PageSubscription.objects.filter(
            user=request.user, page=page
        ).exists()
        subscribers = (
            PageSubscription.objects.filter(page=page)
            .select_related("user", "user__profile")
            .order_by("subscribed_at")
        )

    people = _get_page_people(page)

    can_edit = can_edit_page(request.user, page)
    pending_proposal_count = 0
    if can_edit:
        from wiki.proposals.models import ChangeProposal

        pending_proposal_count = page.proposals.filter(
            status=ChangeProposal.Status.PENDING
        ).count()

    return render(
        request,
        "pages/detail.html",
        {
            "page": page,
            "rendered_content": rendered_content,
            "toc": toc,
            "can_edit": can_edit,
            "pending_proposal_count": pending_proposal_count,
            "breadcrumbs": breadcrumbs,
            "is_subscribed": is_subscribed,
            "subscribers": subscribers,
            "people": people,
        },
    )


@login_required
def page_create(request, path=""):
    """Create a new page, optionally within a directory."""
    from wiki.directories.models import Directory

    directory = None
    if path:
        directory = get_object_or_404(Directory, path=path.strip("/"))

    # Check edit permission on target directory
    if (
        directory
        and directory.path
        and not can_edit_directory(request.user, directory)
    ):
        messages.error(
            request,
            "You don't have permission to create pages here.",
        )
        return redirect(directory.get_absolute_url())

    # Default visibility to match parent directory
    initial = {}
    if directory and directory.visibility != Directory.Visibility.PUBLIC:
        initial["visibility"] = directory.visibility

    form = PageForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)

        # Use directory from location picker if provided
        dir_path = request.POST.get("directory_path", "").strip()
        if dir_path:
            page.directory = _resolve_or_create_directory(
                dir_path, request.user
            )
        else:
            page.directory = directory

        # Validate: page can't be more open than its directory
        if page.directory and is_more_open_than(
            page.visibility, page.directory.visibility
        ):
            messages.error(
                request,
                "A page cannot be more open than its directory. "
                "Change the directory visibility first, or use a "
                "more restrictive setting for this page.",
            )
            dir_segments = []
            if directory:
                d = directory
                while d and d.path:
                    dir_segments.insert(0, {"path": d.path, "title": d.title})
                    d = d.parent
            return render(
                request,
                "pages/form.html",
                {
                    "form": form,
                    "directory": directory,
                    "editing": False,
                    "dir_segments_json": json.dumps(dir_segments),
                },
            )

        # Validate: FLP Staff editability + Private visibility is invalid
        if is_editability_more_open_than_visibility(
            page.editability, page.visibility
        ):
            messages.error(
                request,
                "A page cannot have FLP Staff editability when its "
                "visibility is Private. Change the visibility first, "
                "or use Restricted editability.",
            )
            dir_segments = []
            if directory:
                d = directory
                while d and d.path:
                    dir_segments.insert(0, {"path": d.path, "title": d.title})
                    d = d.parent
            return render(
                request,
                "pages/form.html",
                {
                    "form": form,
                    "directory": directory,
                    "editing": False,
                    "dir_segments_json": json.dumps(dir_segments),
                },
            )

        page.owner = request.user
        page.created_by = request.user
        page.updated_by = request.user
        page.save()

        # Create initial revision
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message=page.change_message or "Initial creation",
            revision_number=1,
            created_by=request.user,
        )

        # Auto-subscribe the creator
        from wiki.subscriptions.models import PageSubscription

        PageSubscription.objects.get_or_create(user=request.user, page=page)

        # Process @mentions
        from wiki.subscriptions.tasks import process_mentions

        mentioned = _extract_mentions(page.content)
        mentioned += _extract_mentions(page.change_message)
        grant_access = _collect_grant_access(request.POST)
        if mentioned:
            process_mentions(
                page.id,
                request.user.id,
                mentioned,
                grant_access_to=grant_access,
            )

        messages.success(request, f'Page "{page.title}" created.')
        return redirect(page.get_absolute_url())

    # Build directory path segments for the location picker
    dir_segments = []
    if directory:
        d = directory
        while d and d.path:
            dir_segments.insert(0, {"path": d.path, "title": d.title})
            d = d.parent

    return render(
        request,
        "pages/form.html",
        {
            "form": form,
            "directory": directory,
            "editing": False,
            "dir_segments_json": json.dumps(dir_segments),
        },
    )


@login_required
def page_edit(request, path):
    """Edit an existing page."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    if not can_edit_page(request.user, page):
        messages.error(request, "You don't have permission to edit this page.")
        return redirect(page.get_absolute_url())

    # Handle lock override POST — acquire lock and redirect to clean edit URL
    if request.method == "POST" and "override_lock" in request.GET:
        acquire_lock_for_page(page, request.user)
        return redirect(
            reverse("page_edit", kwargs={"path": page.content_path})
        )

    # On GET, check for an active lock by another user
    if request.method == "GET":
        lock = get_active_lock_for_page(page, exclude_user=request.user)
        if lock and "override_lock" not in request.GET:
            return render(
                request,
                "edit_lock_warning.html",
                {
                    "lock": lock,
                    "target_title": page.title,
                    "edit_url": reverse(
                        "page_edit",
                        kwargs={"path": page.content_path},
                    ),
                    "cancel_url": page.get_absolute_url(),
                },
            )
        acquire_lock_for_page(page, request.user)

    old_slug = page.slug
    form = PageForm(request.POST or None, instance=page, editing=True)
    if request.method != "POST":
        form.initial["change_message"] = ""
    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)
        page.updated_by = request.user

        # Handle directory change from location picker
        dir_path = request.POST.get("directory_path", "").strip()
        if dir_path:
            page.directory = _resolve_or_create_directory(
                dir_path, request.user
            )
        else:
            page.directory = None

        # Validate: page can't be more open than its directory
        if page.directory and is_more_open_than(
            page.visibility, page.directory.visibility
        ):
            messages.error(
                request,
                "A page cannot be more open than its directory. "
                "Change the directory visibility first, or use a "
                "more restrictive setting for this page.",
            )
            dir_segments = []
            if page.directory:
                d = page.directory
                while d and d.path:
                    dir_segments.insert(0, {"path": d.path, "title": d.title})
                    d = d.parent
            return render(
                request,
                "pages/form.html",
                {
                    "form": form,
                    "page": page,
                    "editing": True,
                    "dir_segments_json": json.dumps(dir_segments),
                },
            )

        # Validate: FLP Staff editability + Private visibility is invalid
        if is_editability_more_open_than_visibility(
            page.editability, page.visibility
        ):
            messages.error(
                request,
                "A page cannot have FLP Staff editability when its "
                "visibility is Private. Change the visibility first, "
                "or use Restricted editability.",
            )
            dir_segments = []
            if page.directory:
                d = page.directory
                while d and d.path:
                    dir_segments.insert(0, {"path": d.path, "title": d.title})
                    d = d.parent
            return render(
                request,
                "pages/form.html",
                {
                    "form": form,
                    "page": page,
                    "editing": True,
                    "dir_segments_json": json.dumps(dir_segments),
                },
            )

        page.save()

        # Create slug redirect if slug changed
        if page.slug != old_slug:
            SlugRedirect.objects.update_or_create(
                old_slug=old_slug,
                defaults={"page": page},
            )

        # Create revision
        last_rev = page.revisions.order_by("-revision_number").first()
        rev_num = (last_rev.revision_number + 1) if last_rev else 1
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message=page.change_message,
            revision_number=rev_num,
            created_by=request.user,
        )

        # Notify subscribers
        from wiki.subscriptions.tasks import (
            notify_subscribers,
            process_mentions,
        )

        notify_subscribers(
            page.id,
            request.user.id,
            page.change_message,
            prev_rev=rev_num - 1 if rev_num > 1 else None,
            new_rev=rev_num,
        )

        # Process @mentions from content + change message
        mentioned = _extract_mentions(page.content)
        mentioned += _extract_mentions(page.change_message)
        grant_access = _collect_grant_access(request.POST)
        if mentioned:
            process_mentions(
                page.id,
                request.user.id,
                mentioned,
                grant_access_to=grant_access,
            )

        release_lock_for_page(page)
        messages.success(request, f'Page "{page.title}" updated.')
        return redirect(page.get_absolute_url())

    # Build directory path segments for the location picker
    dir_segments = []
    if page.directory:
        d = page.directory
        while d and d.path:
            dir_segments.insert(0, {"path": d.path, "title": d.title})
            d = d.parent

    return render(
        request,
        "pages/form.html",
        {
            "form": form,
            "page": page,
            "editing": True,
            "dir_segments_json": json.dumps(dir_segments),
        },
    )


@login_required
def page_move(request, path):
    """Move a page to a different directory."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    if not can_edit_page(request.user, page):
        messages.error(request, "You don't have permission to move this page.")
        return redirect(page.get_absolute_url())

    from .forms import PageMoveForm

    initial = {"directory": page.directory}
    form = PageMoveForm(
        request.POST or None,
        initial=initial,
        exclude_current=page.directory,
    )

    if request.method == "POST" and form.is_valid():
        new_directory = form.cleaned_data["directory"]

        # Validate: page can't be more open than its new directory
        if new_directory and is_more_open_than(
            page.visibility, new_directory.visibility
        ):
            messages.error(
                request,
                "Cannot move a page into a more restrictive directory. "
                "Change the page visibility first, or choose a "
                "directory that matches.",
            )
            return render(
                request,
                "pages/move.html",
                {"form": form, "page": page},
            )

        page.directory = new_directory
        page.save()
        messages.success(
            request,
            f'Moved "{page.title}" to /{new_directory.path}.'
            if new_directory
            else f'Moved "{page.title}" to root.',
        )
        return redirect(page.get_absolute_url())

    return render(
        request,
        "pages/move.html",
        {"form": form, "page": page},
    )


@login_required
def page_delete(request, path):
    """Delete a page (owner/admin only)."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    from wiki.lib.permissions import is_system_owner

    if page.owner != request.user and not is_system_owner(request.user):
        messages.error(
            request, "You don't have permission to delete this page."
        )
        return redirect(page.get_absolute_url())

    incoming_links = list(
        page.incoming_links.select_related("from_page", "from_page__directory")
    )

    if request.method == "POST":
        if incoming_links:
            messages.error(
                request,
                "Cannot delete this page because other pages link to it.",
            )
            return redirect(reverse("page_delete", kwargs={"path": path}))

        title = page.title
        redirect_url = (
            page.directory.get_absolute_url()
            if page.directory
            else reverse("root")
        )
        page.delete()
        messages.success(request, f'Page "{title}" deleted.')
        return redirect(redirect_url)

    return render(
        request,
        "pages/delete_confirm.html",
        {"page": page, "incoming_links": incoming_links},
    )


@login_required
def page_permissions(request, path):
    """Manage permissions for a page."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    if not can_edit_page(request.user, page):
        messages.error(
            request, "You don't have permission to manage this page."
        )
        return redirect(page.get_absolute_url())

    from django.contrib.auth.models import User

    from .forms import PagePermissionForm

    # Handle remove
    if request.method == "POST" and "remove" in request.POST:
        perm_id = request.POST.get("remove")
        PagePermission.objects.filter(pk=perm_id, page=page).delete()
        messages.success(request, "Permission removed.")
        return redirect(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            )
        )

    # Handle add
    form = PagePermissionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        target_type = request.POST.get("target_type", "user")
        perm_type = form.cleaned_data["permission_type"]

        if target_type == "group":
            group = form.cleaned_data.get("group")
            if group:
                _, created = PagePermission.objects.get_or_create(
                    page=page,
                    group=group,
                    permission_type=perm_type,
                    defaults={"user": None},
                )
                if created:
                    messages.success(
                        request,
                        f"Granted {perm_type} access to group {group.name}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Group {group.name} already has {perm_type} access.",
                    )
            else:
                messages.error(request, "Please select a group.")
        else:
            username = form.cleaned_data.get("username", "").strip()
            if not username:
                messages.error(request, "Please enter a username.")
            else:
                user = User.objects.filter(
                    email__istartswith=username + "@"
                ).first()
                if not user:
                    messages.error(
                        request,
                        f'No user found with username "{username}".',
                    )
                else:
                    _, created = PagePermission.objects.get_or_create(
                        page=page,
                        user=user,
                        permission_type=perm_type,
                    )
                    if created:
                        messages.success(
                            request,
                            f"Granted {perm_type} access to {username}.",
                        )
                    else:
                        messages.info(
                            request,
                            f"{username} already has {perm_type} access.",
                        )

        return redirect(
            reverse(
                "page_permissions",
                kwargs={"path": page.content_path},
            )
        )

    user_perms = (
        page.permissions.filter(user__isnull=False)
        .select_related("user", "user__profile")
        .order_by("permission_type", "user__email")
    )
    group_perms = (
        page.permissions.filter(group__isnull=False)
        .select_related("group")
        .order_by("permission_type", "group__name")
    )

    return render(
        request,
        "pages/permissions.html",
        {
            "page": page,
            "form": form,
            "user_permissions": user_perms,
            "group_permissions": group_perms,
        },
    )


def page_history(request, path):
    """Show revision history for a page."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    revisions = page.revisions.select_related("created_by").all()
    diff_base = page.get_absolute_url() + "/diff/"
    return render(
        request,
        "pages/history.html",
        {"page": page, "revisions": revisions, "diff_base": diff_base},
    )


def page_diff(request, path, v1, v2):
    """Show diff between two versions."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    rev1 = get_object_or_404(PageRevision, page=page, revision_number=v1)
    rev2 = get_object_or_404(PageRevision, page=page, revision_number=v2)

    from .diff_utils import unified_diff

    diff_html = unified_diff(rev1.content, rev2.content)

    return render(
        request,
        "pages/diff.html",
        {
            "page": page,
            "rev1": rev1,
            "rev2": rev2,
            "diff_html": diff_html,
            "can_edit": can_edit_page(request.user, page),
        },
    )


@login_required
def page_revert(request, path, rev_num):
    """Revert a page to a previous revision (creates a new revision)."""
    segments = path.strip("/").split("/")
    slug = segments[-1]
    page = get_object_or_404(Page, slug=slug)

    if not can_edit_page(request.user, page):
        messages.error(request, "You don't have permission to edit this page.")
        return redirect(page.get_absolute_url())

    old_rev = get_object_or_404(
        PageRevision, page=page, revision_number=rev_num
    )

    if request.method == "POST":
        page.title = old_rev.title
        page.content = old_rev.content
        page.change_message = f"Reverted to version {rev_num}"
        page.updated_by = request.user
        page.save()

        last_rev = page.revisions.order_by("-revision_number").first()
        new_rev_num = (last_rev.revision_number + 1) if last_rev else 1
        PageRevision.objects.create(
            page=page,
            title=page.title,
            content=page.content,
            change_message=page.change_message,
            revision_number=new_rev_num,
            created_by=request.user,
        )

        messages.success(
            request,
            f'Reverted "{page.title}" to version {rev_num}.',
        )
        return redirect(page.get_absolute_url())

    return render(
        request,
        "pages/revert_confirm.html",
        {"page": page, "revision": old_rev},
    )


@require_POST
@login_required
def check_page_permissions(request):
    """Check mentioned users' access and linked pages' visibility.

    POST JSON: {
        page_slug: "...",
        usernames: ["mike", "bob"],
        linked_slugs: ["internal-doc", "secret-page"]
    }
    Returns: {
        users_without_access: [{username, display_name}],
        restrictive_links: [{slug, title, visibility, permissions_url}]
    }
    """
    import json as json_mod

    try:
        data = json_mod.loads(request.body)
    except (json_mod.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    page_slug = data.get("page_slug", "")
    usernames = data.get("usernames", [])
    linked_slugs = data.get("linked_slugs", [])

    from django.contrib.auth.models import User

    # Check mentioned users
    users_without_access = []
    page = Page.objects.filter(slug=page_slug).first()

    if page and page.visibility != Page.Visibility.PUBLIC:
        for uname in usernames:
            email = f"{uname}@free.law"
            user = User.objects.filter(email=email).first()
            if user and not can_view_page(user, page):
                name = uname
                if hasattr(user, "profile") and user.profile.display_name:
                    name = user.profile.display_name
                users_without_access.append(
                    {"username": uname, "display_name": name}
                )

    # Check linked pages
    restrictive_links = []
    if linked_slugs and page:
        current_visibility = page.visibility
        for slug in set(linked_slugs):
            if slug == page_slug:
                continue
            linked = Page.objects.filter(slug=slug).first()
            if not linked:
                continue
            # Flag if current page is more open than the linked page
            if is_more_open_than(current_visibility, linked.visibility):
                restrictive_links.append(
                    {
                        "slug": linked.slug,
                        "title": linked.title,
                        "visibility": linked.visibility,
                        "permissions_url": reverse(
                            "page_permissions",
                            kwargs={"path": linked.content_path},
                        ),
                    }
                )

    return JsonResponse(
        {
            "users_without_access": users_without_access,
            "restrictive_links": restrictive_links,
        }
    )


# Keep old name as alias for backwards compatibility
check_mention_permissions = check_page_permissions


@require_POST
@login_required
def page_preview_htmx(request):
    """Return rendered markdown preview for HTMX requests."""
    content = request.POST.get("content", "")
    rendered = render_markdown(content)
    return HttpResponse(rendered)


@require_POST
@login_required
def file_upload_htmx(request):
    """Handle file upload via HTMX, return markdown syntax."""

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse({"error": "No file provided"}, status=400)

    max_size = 1024 * 1024 * 1024  # 1 GB
    if uploaded_file.size > max_size:
        return JsonResponse(
            {"error": "File too large. Maximum size is 1 GB."}, status=400
        )

    upload = FileUpload.objects.create(
        uploaded_by=request.user,
        file=uploaded_file,
        original_filename=uploaded_file.name,
        content_type=uploaded_file.content_type or "",
    )

    # Return markdown syntax for the uploaded file
    file_url = reverse(
        "file_serve",
        kwargs={
            "file_id": upload.id,
            "filename": upload.original_filename,
        },
    )
    if upload.content_type and upload.content_type.startswith("image/"):
        md = f"![{upload.original_filename}]({file_url})"
    else:
        md = f"[{upload.original_filename}]({file_url})"

    return JsonResponse({"markdown": md})


def file_serve(request, file_id, filename):
    """Serve a file with permission checks. Redirect to signed S3 URL."""
    upload = get_object_or_404(FileUpload, id=file_id)

    # If file is attached to a page, check page permissions
    if upload.page and not can_view_page(request.user, upload.page):
        raise Http404

    # In development, serve directly; in production, redirect to S3
    from django.conf import settings

    if settings.DEBUG:
        from django.http import FileResponse

        return FileResponse(upload.file.open("rb"))

    # Generate a signed S3 URL and redirect
    url = upload.file.storage.url(upload.file.name)
    return redirect(url)


@login_required
def page_search_htmx(request):
    """HTMX endpoint for page title autocomplete."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return HttpResponse("")

    qs = Page.objects.filter(title__icontains=q)
    exclude_slug = request.GET.get("exclude", "").strip()
    if exclude_slug:
        qs = qs.exclude(slug=exclude_slug)
    pages = qs.values("title", "slug")[:10]

    html = ""
    for p in pages:
        html += (
            f'<div class="px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700'
            f' cursor-pointer" data-slug="{p["slug"]}">'
            f"{p['title']}</div>"
        )

    return HttpResponse(html)
