from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from wiki.lib.edit_lock import (
    acquire_lock_for_directory,
    get_active_lock_for_directory,
    release_lock_for_directory,
)
from wiki.lib.markdown import render_markdown
from wiki.lib.permissions import (
    can_edit_directory,
    can_view_directory,
    can_view_page,
    is_editability_more_open_than_visibility,
)

from .models import Directory, DirectoryRevision


def _create_revision(directory, user, change_message=""):
    """Create a new DirectoryRevision for the given directory."""
    last = directory.revisions.order_by("-revision_number").first()
    rev_num = (last.revision_number + 1) if last else 1
    return DirectoryRevision.objects.create(
        directory=directory,
        title=directory.title,
        description=directory.description,
        visibility=directory.visibility,
        editability=directory.editability,
        change_message=change_message,
        revision_number=rev_num,
        created_by=user,
    )


def _get_sort_config(request):
    """Read and validate the sort parameter from the request."""
    ALLOWED_SORTS = {"title", "updated", "created", "views"}
    sort = request.GET.get("sort", "title")
    if sort not in ALLOWED_SORTS:
        sort = "title"
    return sort


def _sort_pages(pages, sort):
    """Sort a list of pages by the given sort key."""
    if sort == "updated":
        return sorted(pages, key=lambda p: p.updated_at, reverse=True)
    elif sort == "created":
        return sorted(pages, key=lambda p: p.created_at, reverse=True)
    elif sort == "views":
        return sorted(pages, key=lambda p: p.view_count, reverse=True)
    return sorted(pages, key=lambda p: p.title.lower())


def _sort_directories(dirs, sort):
    """Sort a list of directories by the given sort key."""
    if sort == "updated":
        return sorted(dirs, key=lambda d: d.updated_at, reverse=True)
    elif sort == "created":
        return sorted(dirs, key=lambda d: d.created_at, reverse=True)
    # "views" and "title" both sort dirs by title
    return sorted(dirs, key=lambda d: d.title.lower())


def root_view(request):
    """Root directory view — shows top-level directories and pages."""
    root, _ = Directory.objects.get_or_create(
        path="", defaults={"title": "Home"}
    )
    all_subdirs = Directory.objects.filter(
        Q(parent=root) | Q(parent__isnull=True)
    ).exclude(path="")

    # Filter subdirectories by view permission
    subdirectories = [
        d for d in all_subdirs if can_view_directory(request.user, d)
    ]

    # Show pages in root directory + unassigned pages
    from wiki.pages.models import Page

    pages = Page.objects.filter(Q(directory=root) | Q(directory__isnull=True))

    # Filter by view permission
    visible_pages = [p for p in pages if can_view_page(request.user, p)]

    sort = _get_sort_config(request)
    subdirectories = _sort_directories(subdirectories, sort)
    visible_pages = _sort_pages(visible_pages, sort)

    rendered_description = ""
    if root.description:
        rendered_description = render_markdown(root.description)

    return render(
        request,
        "directories/detail.html",
        {
            "directory": root,
            "subdirectories": subdirectories,
            "pages": visible_pages,
            "breadcrumbs": [("Home", reverse("root"))],
            "current_sort": sort,
            "rendered_description": rendered_description,
            "can_edit": can_edit_directory(request.user, root),
        },
    )


@login_required
def directory_edit_root(request):
    """Edit the root directory's title and description."""
    root = get_object_or_404(Directory, path="")

    if not can_edit_directory(request.user, root):
        messages.error(
            request,
            "You don't have permission to edit this directory.",
        )
        return redirect(reverse("root"))

    # Handle lock override POST — acquire lock and redirect to clean edit URL
    if request.method == "POST" and "override_lock" in request.GET:
        acquire_lock_for_directory(root, request.user)
        return redirect(reverse("directory_edit_root"))

    # On GET, check for an active lock by another user
    if request.method == "GET":
        lock = get_active_lock_for_directory(root, exclude_user=request.user)
        if lock and "override_lock" not in request.GET:
            return render(
                request,
                "edit_lock_warning.html",
                {
                    "lock": lock,
                    "target_title": root.title,
                    "edit_url": reverse("directory_edit_root"),
                    "cancel_url": reverse("root"),
                },
            )
        acquire_lock_for_directory(root, request.user)

    from .forms import DirectoryForm

    form = DirectoryForm(request.POST or None, instance=root)
    if request.method == "POST" and form.is_valid():
        form.save()
        _create_revision(
            root, request.user, form.cleaned_data.get("change_message", "")
        )
        release_lock_for_directory(root)
        messages.success(request, f'Directory "{root.title}" updated.')
        return redirect(reverse("root"))

    return render(
        request,
        "directories/form.html",
        {"form": form, "directory": root},
    )


def directory_detail(request, path):
    """Display a directory's contents."""
    directory = Directory.objects.filter(path=path.strip("/")).first()

    if directory is None:
        # Not a directory — let the page catch-all handle it
        raise Http404

    # Directory gate: hide existence from unauthorized users
    if not can_view_directory(request.user, directory):
        raise Http404

    all_subdirs = directory.children.all()
    subdirectories = [
        d for d in all_subdirs if can_view_directory(request.user, d)
    ]
    pages = directory.pages.all()
    visible_pages = [p for p in pages if can_view_page(request.user, p)]

    sort = _get_sort_config(request)
    subdirectories = _sort_directories(subdirectories, sort)
    visible_pages = _sort_pages(visible_pages, sort)

    rendered_description = ""
    if directory.description:
        rendered_description = render_markdown(directory.description)

    return render(
        request,
        "directories/detail.html",
        {
            "directory": directory,
            "subdirectories": subdirectories,
            "pages": visible_pages,
            "breadcrumbs": directory.get_breadcrumbs(),
            "rendered_description": rendered_description,
            "can_edit": can_edit_directory(request.user, directory),
            "current_sort": sort,
        },
    )


@login_required
def directory_edit(request, path):
    """Edit a directory's title and description."""
    directory = get_object_or_404(Directory, path=path.strip("/"))

    if not can_edit_directory(request.user, directory):
        messages.error(
            request,
            "You don't have permission to edit this directory.",
        )
        return redirect(directory.get_absolute_url())

    edit_url = reverse("directory_edit", kwargs={"path": directory.path})

    # Handle lock override POST — acquire lock and redirect to clean edit URL
    if request.method == "POST" and "override_lock" in request.GET:
        acquire_lock_for_directory(directory, request.user)
        return redirect(edit_url)

    # On GET, check for an active lock by another user
    if request.method == "GET":
        lock = get_active_lock_for_directory(
            directory, exclude_user=request.user
        )
        if lock and "override_lock" not in request.GET:
            return render(
                request,
                "edit_lock_warning.html",
                {
                    "lock": lock,
                    "target_title": directory.title,
                    "edit_url": edit_url,
                    "cancel_url": directory.get_absolute_url(),
                },
            )
        acquire_lock_for_directory(directory, request.user)

    from .forms import DirectoryForm

    form = DirectoryForm(request.POST or None, instance=directory)
    if request.method == "POST" and form.is_valid():
        # Validate: FLP Staff editability + Private visibility is invalid
        if is_editability_more_open_than_visibility(
            form.cleaned_data["editability"],
            form.cleaned_data["visibility"],
        ):
            messages.error(
                request,
                "A directory cannot have FLP Staff editability when "
                "its visibility is Private. Change the visibility "
                "first, or use Restricted editability.",
            )
            return render(
                request,
                "directories/form.html",
                {"form": form, "directory": directory},
            )

        form.save()
        _create_revision(
            directory,
            request.user,
            form.cleaned_data.get("change_message", ""),
        )
        release_lock_for_directory(directory)
        messages.success(request, f'Directory "{directory.title}" updated.')
        return redirect(directory.get_absolute_url())

    return render(
        request,
        "directories/form.html",
        {"form": form, "directory": directory},
    )


@login_required
def directory_create(request, path=""):
    """Create a new subdirectory."""
    from .forms import DirectoryCreateForm

    if path:
        parent = get_object_or_404(Directory, path=path.strip("/"))
    else:
        parent, _ = Directory.objects.get_or_create(
            path="", defaults={"title": "Home"}
        )

    # Check edit permission on parent directory
    if parent.path and not can_edit_directory(request.user, parent):
        messages.error(
            request,
            "You don't have permission to create directories here.",
        )
        return redirect(parent.get_absolute_url())

    form = DirectoryCreateForm(request.POST or None, parent=parent)
    if request.method == "POST" and form.is_valid():
        directory = form.save(commit=False)
        directory.parent = parent
        directory.owner = request.user
        directory.created_by = request.user

        # Validate: FLP Staff editability + Private visibility is invalid
        if is_editability_more_open_than_visibility(
            directory.editability, directory.visibility
        ):
            messages.error(
                request,
                "A directory cannot have FLP Staff editability when "
                "its visibility is Private. Change the visibility "
                "first, or use Restricted editability.",
            )
            return render(
                request,
                "directories/form.html",
                {
                    "form": form,
                    "parent": parent,
                    "creating": True,
                },
            )

        # Build the full path
        if parent and parent.path:
            directory.path = f"{parent.path}/{directory.path}"
        directory.save()
        _create_revision(directory, request.user, "Initial creation")
        messages.success(
            request,
            f'Directory "{directory.title}" created.',
        )
        return redirect(directory.get_absolute_url())

    return render(
        request,
        "directories/form.html",
        {
            "form": form,
            "parent": parent,
            "creating": True,
        },
    )


def _get_permissions_url(directory):
    """Return the URL for a directory's permissions page."""
    if directory.path:
        return reverse(
            "directory_permissions",
            kwargs={"path": directory.path},
        )
    return reverse("directory_permissions_root")


def _directory_permissions_inner(request, directory):
    """Shared logic for managing directory permissions."""
    if not can_edit_directory(request.user, directory):
        messages.error(
            request,
            "You don't have permission to manage this directory.",
        )
        return redirect(directory.get_absolute_url())

    from django.contrib.auth.models import User

    from .forms import DirectoryPermissionForm
    from .models import DirectoryPermission

    perms_url = _get_permissions_url(directory)

    # Handle remove
    if request.method == "POST" and "remove" in request.POST:
        perm_id = request.POST.get("remove")
        DirectoryPermission.objects.filter(
            pk=perm_id, directory=directory
        ).delete()
        messages.success(request, "Permission removed.")
        return redirect(perms_url)

    # Handle add
    form = DirectoryPermissionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        target_type = request.POST.get("target_type", "user")
        perm_type = form.cleaned_data["permission_type"]

        if target_type == "group":
            group = form.cleaned_data.get("group")
            if group:
                _, created = DirectoryPermission.objects.get_or_create(
                    directory=directory,
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
                    _, created = DirectoryPermission.objects.get_or_create(
                        directory=directory,
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
        return redirect(perms_url)

    user_perms = (
        directory.permissions.filter(user__isnull=False)
        .select_related("user", "user__profile")
        .order_by("permission_type", "user__email")
    )
    group_perms = (
        directory.permissions.filter(group__isnull=False)
        .select_related("group")
        .order_by("permission_type", "group__name")
    )

    return render(
        request,
        "directories/permissions.html",
        {
            "directory": directory,
            "form": form,
            "user_permissions": user_perms,
            "group_permissions": group_perms,
        },
    )


@login_required
def directory_permissions(request, path):
    """Manage permissions for a directory."""
    directory = get_object_or_404(Directory, path=path.strip("/"))
    return _directory_permissions_inner(request, directory)


@login_required
def directory_permissions_root(request):
    """Manage permissions for the root directory."""
    root = get_object_or_404(Directory, path="")
    return _directory_permissions_inner(request, root)


@login_required
def directory_move(request, path):
    """Move a directory to a new parent."""
    directory = get_object_or_404(Directory, path=path.strip("/"))

    if not can_edit_directory(request.user, directory):
        messages.error(
            request,
            "You don't have permission to move this directory.",
        )
        return redirect(directory.get_absolute_url())

    from .forms import DirectoryMoveForm

    initial = {"parent": directory.parent}
    form = DirectoryMoveForm(
        request.POST or None,
        initial=initial,
        directory=directory,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        new_parent = form.cleaned_data["parent"]
        _move_directory(directory, new_parent)
        messages.success(
            request,
            f'Moved "{directory.title}" to {new_parent.title}.',
        )
        return redirect(directory.get_absolute_url())

    return render(
        request,
        "directories/move.html",
        {"form": form, "directory": directory},
    )


def _move_directory(directory, new_parent):
    """Move a directory to a new parent, updating all descendant paths."""
    from django.utils.text import slugify

    directory.parent = new_parent
    slug = slugify(directory.title)
    if new_parent.path:
        directory.path = f"{new_parent.path}/{slug}"
    else:
        directory.path = slug
    directory.save()
    _update_descendant_paths(directory)


def _update_descendant_paths(directory):
    """Recursively update paths of all descendants."""
    from django.utils.text import slugify

    for child in directory.children.all():
        slug = slugify(child.title)
        if directory.path:
            child.path = f"{directory.path}/{slug}"
        else:
            child.path = slug
        child.save()
        _update_descendant_paths(child)


@login_required
def directory_delete(request, path):
    """Delete a directory (must be empty)."""
    directory = get_object_or_404(Directory, path=path.strip("/"))

    if not can_edit_directory(request.user, directory):
        messages.error(
            request,
            "You don't have permission to delete this directory.",
        )
        return redirect(directory.get_absolute_url())

    has_children = directory.children.exists()
    has_pages = directory.pages.exists()

    if request.method == "POST":
        if has_children or has_pages:
            messages.error(
                request,
                "Cannot delete a directory that contains pages or "
                "subdirectories.",
            )
            return redirect(directory.get_absolute_url())

        title = directory.title
        parent_url = (
            directory.parent.get_absolute_url()
            if directory.parent
            else reverse("root")
        )
        directory.delete()
        messages.success(request, f'Directory "{title}" deleted.')
        return redirect(parent_url)

    return render(
        request,
        "directories/delete_confirm.html",
        {
            "directory": directory,
            "has_children": has_children,
            "has_pages": has_pages,
        },
    )


@login_required
def directory_search_htmx(request):
    """JSON endpoint for directory autocomplete.

    Query params:
      q: search term for directory title/path
      parent: parent directory path to scope search (optional)

    Returns JSON list of {path, title} objects.
    """
    q = request.GET.get("q", "").strip()
    parent_path = request.GET.get("parent", "").strip()

    qs = Directory.objects.exclude(path="").order_by("path")

    if parent_path:
        qs = qs.filter(parent__path=parent_path)
    else:
        # Search children of root (or orphaned top-level dirs)
        qs = qs.filter(Q(parent__path="") | Q(parent__isnull=True))

    if q:
        qs = qs.filter(title__icontains=q)

    # SECURITY: filter results by permission so private directories are
    # never revealed in autocomplete to users who lack access.
    results = []
    for d in qs.iterator():
        if can_view_directory(request.user, d):
            results.append({"path": d.path, "title": d.title})
        if len(results) >= 15:
            break

    return JsonResponse(results, safe=False)


def _directory_apply_permissions_inner(request, directory):
    """Shared logic for applying directory permissions to children."""
    if not can_edit_directory(request.user, directory):
        messages.error(
            request,
            "You don't have permission to manage this directory.",
        )
        return redirect(directory.get_absolute_url())

    from .models import DirectoryPermission

    direct_pages = directory.pages.all()

    if request.method == "POST":
        scope = request.POST.get("scope", "direct")
        dir_perms = directory.permissions.all()

        def apply_to_pages(pages, source_dir):
            """Apply directory permissions to a set of pages."""
            from wiki.pages.models import PagePermission

            for page in pages:
                page.visibility = source_dir.visibility
                page.editability = source_dir.editability
                page.save(update_fields=["visibility", "editability"])
                for dp in dir_perms:
                    kwargs = {
                        "page": page,
                        "permission_type": dp.permission_type,
                    }
                    if dp.user_id:
                        kwargs["user"] = dp.user
                        kwargs["defaults"] = {"group": None}
                    else:
                        kwargs["group"] = dp.group
                        kwargs["defaults"] = {"user": None}
                    PagePermission.objects.get_or_create(**kwargs)

        def apply_to_dirs_recursive(parent_dir):
            """Recursively apply permissions to child directories."""
            for child in parent_dir.children.all():
                child.visibility = directory.visibility
                child.editability = directory.editability
                child.save(update_fields=["visibility", "editability"])
                for dp in dir_perms:
                    kwargs = {
                        "directory": child,
                        "permission_type": dp.permission_type,
                    }
                    if dp.user_id:
                        kwargs["user"] = dp.user
                        kwargs["defaults"] = {"group": None}
                    else:
                        kwargs["group"] = dp.group
                        kwargs["defaults"] = {"user": None}
                    DirectoryPermission.objects.get_or_create(**kwargs)
                # Apply to pages in this child directory
                apply_to_pages(child.pages.all(), directory)
                # Recurse
                apply_to_dirs_recursive(child)

        # Always apply to direct child pages
        apply_to_pages(direct_pages, directory)

        if scope == "recursive":
            apply_to_dirs_recursive(directory)
            messages.success(
                request,
                "Permissions applied recursively to all pages "
                "and subdirectories.",
            )
        else:
            messages.success(
                request,
                "Permissions applied to direct child pages.",
            )

        return redirect(_get_permissions_url(directory))

    # GET: show confirmation page
    def count_recursive(d):
        pages = d.pages.count()
        dirs = d.children.count()
        for child in d.children.all():
            cp, cd = count_recursive(child)
            pages += cp
            dirs += cd
        return pages, dirs

    total_pages, total_dirs = count_recursive(directory)
    direct_page_count = direct_pages.count()

    return render(
        request,
        "directories/apply_permissions.html",
        {
            "directory": directory,
            "direct_page_count": direct_page_count,
            "total_page_count": total_pages,
            "total_dir_count": total_dirs,
        },
    )


@login_required
def directory_apply_permissions(request, path):
    """Apply directory permissions to child pages and subdirectories."""
    directory = get_object_or_404(Directory, path=path.strip("/"))
    return _directory_apply_permissions_inner(request, directory)


@login_required
def directory_apply_permissions_root(request):
    """Apply root directory permissions to child pages and subdirectories."""
    root = get_object_or_404(Directory, path="")
    return _directory_apply_permissions_inner(request, root)


def _get_history_url(directory):
    """Return the history URL for a directory."""
    if directory.path:
        return reverse("directory_history", kwargs={"path": directory.path})
    return reverse("directory_history_root")


def _get_diff_base(directory):
    """Return the base URL for directory diff (without version numbers)."""
    if directory.path:
        return reverse(
            "directory_diff",
            kwargs={"path": directory.path, "v1": 0, "v2": 0},
        ).rsplit("0/0/", 1)[0]
    return reverse("directory_diff_root", kwargs={"v1": 0, "v2": 0}).rsplit(
        "0/0/", 1
    )[0]


def _directory_history_inner(request, directory):
    """Shared logic for directory history view."""
    if not can_view_directory(request.user, directory):
        raise Http404

    revisions = directory.revisions.select_related("created_by").order_by(
        "-revision_number"
    )

    return render(
        request,
        "directories/history.html",
        {
            "directory": directory,
            "revisions": revisions,
            "diff_base": _get_diff_base(directory),
        },
    )


def directory_history(request, path):
    """Show revision history for a directory."""
    directory = get_object_or_404(Directory, path=path.strip("/"))
    return _directory_history_inner(request, directory)


def directory_history_root(request):
    """Show revision history for the root directory."""
    root = get_object_or_404(Directory, path="")
    return _directory_history_inner(request, root)


def _directory_diff_inner(request, directory, v1, v2):
    """Shared logic for directory diff view."""
    from wiki.pages.diff_utils import unified_diff

    if not can_view_directory(request.user, directory):
        raise Http404

    rev1 = get_object_or_404(
        DirectoryRevision, directory=directory, revision_number=v1
    )
    rev2 = get_object_or_404(
        DirectoryRevision, directory=directory, revision_number=v2
    )

    # Description diff
    diff_html = unified_diff(rev1.description, rev2.description)

    # Metadata change summary
    meta_changes = []
    if rev1.title != rev2.title:
        meta_changes.append(f'Title: "{rev1.title}" → "{rev2.title}"')
    if rev1.visibility != rev2.visibility:
        meta_changes.append(
            f"Visibility: {rev1.visibility} → {rev2.visibility}"
        )
    if rev1.editability != rev2.editability:
        meta_changes.append(
            f"Editability: {rev1.editability} → {rev2.editability}"
        )

    if directory.path:
        revert_url = reverse(
            "directory_revert",
            kwargs={
                "path": directory.path,
                "rev_num": rev1.revision_number,
            },
        )
    else:
        revert_url = reverse(
            "directory_revert_root",
            kwargs={"rev_num": rev1.revision_number},
        )

    return render(
        request,
        "directories/diff.html",
        {
            "directory": directory,
            "rev1": rev1,
            "rev2": rev2,
            "diff_html": diff_html,
            "meta_changes": meta_changes,
            "can_edit": can_edit_directory(request.user, directory),
            "history_url": _get_history_url(directory),
            "revert_url": revert_url,
        },
    )


def directory_diff(request, path, v1, v2):
    """Show diff between two directory revisions."""
    directory = get_object_or_404(Directory, path=path.strip("/"))
    return _directory_diff_inner(request, directory, v1, v2)


def directory_diff_root(request, v1, v2):
    """Show diff between two root directory revisions."""
    root = get_object_or_404(Directory, path="")
    return _directory_diff_inner(request, root, v1, v2)


def _directory_revert_inner(request, directory, rev_num):
    """Shared logic for directory revert view."""
    if not can_edit_directory(request.user, directory):
        messages.error(
            request,
            "You don't have permission to revert this directory.",
        )
        return redirect(directory.get_absolute_url())

    revision = get_object_or_404(
        DirectoryRevision, directory=directory, revision_number=rev_num
    )

    if request.method == "POST":
        directory.title = revision.title
        directory.description = revision.description
        directory.visibility = revision.visibility
        directory.editability = revision.editability
        directory.save()
        _create_revision(
            directory,
            request.user,
            f"Reverted to v{rev_num}",
        )
        messages.success(
            request,
            f'Reverted "{directory.title}" to v{rev_num}.',
        )
        return redirect(directory.get_absolute_url())

    history_url = _get_history_url(directory)
    return render(
        request,
        "directories/revert_confirm.html",
        {
            "directory": directory,
            "revision": revision,
            "history_url": history_url,
        },
    )


@login_required
def directory_revert(request, path, rev_num):
    """Revert a directory to a previous revision."""
    directory = get_object_or_404(Directory, path=path.strip("/"))
    return _directory_revert_inner(request, directory, rev_num)


@login_required
def directory_revert_root(request, rev_num):
    """Revert the root directory to a previous revision."""
    root = get_object_or_404(Directory, path="")
    return _directory_revert_inner(request, root, rev_num)


@login_required
def page_create_in_directory(request, path):
    """Create a new page within a directory."""
    from wiki.pages.views import page_create

    return page_create(request, path=path)
