import json
import re
import uuid
from datetime import datetime
from pathlib import Path as FilePath

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from wiki.comments.models import PageComment
from wiki.directories.models import Directory, DirectoryPermission
from wiki.lib.data_source import fetch_page_data, substitute_data_variables
from wiki.lib.edit_lock import (
    acquire_lock_for_page,
    get_active_lock_for_page,
    release_lock_for_page,
)
from wiki.lib.inheritance import resolve_effective_value
from wiki.lib.markdown import render_markdown
from wiki.lib.path_utils import page_path_conflicts_with_directory
from wiki.lib.permissions import (
    can_edit_directory,
    can_edit_page,
    can_view_directory,
    can_view_page,
    is_system_owner,
    viewable_pages_q,
)
from wiki.lib.ratelimiter import ratelimit_search, ratelimit_upload
from wiki.lib.seo import (
    build_article_jsonld,
    build_breadcrumbs_jsonld,
    extract_description,
)
from wiki.lib.storage import get_s3_client
from wiki.proposals.models import ChangeProposal
from wiki.subscriptions.models import PageSubscription
from wiki.subscriptions.tasks import notify_subscribers, process_mentions
from wiki.subscriptions.utils import (
    get_effective_watchers_for_page,
    is_effectively_subscribed_to_page,
)

from .diff_utils import unified_diff
from .forms import PageForm, PageMoveForm, PagePermissionForm
from .models import (
    FileUpload,
    Page,
    PagePermission,
    PageRevision,
    PageViewTally,
    PendingUpload,
    SlugRedirect,
)

FILE_REF_RE = re.compile(r"/files/(\d+)/")


def _link_uploads_to_page(page, user):
    """Link FileUpload records referenced in page content to this page.

    Parses /files/<id>/ references from the page's markdown content and
    sets FileUpload.page for any unlinked uploads that the editing user
    owns.  Also unlinks uploads previously attached to this page that are
    no longer referenced by the current content *or* any past revision
    (so that revisions remain restorable).

    Security: only orphaned uploads belonging to ``user`` are linked,
    preventing a user from claiming another user's upload by guessing
    its ID and embedding it in their page.
    """
    referenced_ids = set(int(m) for m in FILE_REF_RE.findall(page.content))

    if referenced_ids:
        FileUpload.objects.filter(
            id__in=referenced_ids, page__isnull=True, uploaded_by=user
        ).update(page=page)

    # Collect file IDs referenced by any revision of this page.
    revision_ids = set()
    for content in page.revisions.values_list("content", flat=True):
        revision_ids.update(int(m) for m in FILE_REF_RE.findall(content))

    # Only unlink uploads not referenced by current content OR any
    # past revision, so that older revisions can still be restored.
    keep_ids = referenced_ids | revision_ids
    stale = FileUpload.objects.filter(page=page).exclude(id__in=keep_ids)
    stale.update(page=None)


def _parse_page_path(path: str) -> str:
    """Return the page slug from a URL path."""
    return path.strip("/").split("/")[-1]


def _build_dir_segments(directory):
    """Build breadcrumb path segments for a directory."""
    segments = []
    d = directory
    while d and d.path:
        segments.insert(0, {"path": d.path, "title": d.title})
        d = d.parent
    return segments


def _resolve_directory_from_post(post_data):
    """Find the closest existing Directory for a posted directory_path.

    If the exact path exists, return that directory.  Otherwise walk up
    the path to find the deepest existing ancestor (needed when the user
    created a new directory segment in the location picker that hasn't
    been persisted yet).  Returns ``None`` only when no ancestor exists.
    """
    dir_path = post_data.get("directory_path", "").strip()
    if not dir_path:
        return None
    directory = Directory.objects.filter(path=dir_path).first()
    if directory:
        return directory
    segments = dir_path.strip("/").split("/")
    for i in range(len(segments) - 1, 0, -1):
        ancestor_path = "/".join(segments[:i])
        ancestor = Directory.objects.filter(path=ancestor_path).first()
        if ancestor:
            return ancestor
    return Directory.objects.filter(path="").first()


def _build_dir_segments_from_post(post_data):
    """Reconstruct location picker segments from POST data.

    Used when re-rendering the form after validation failure so the
    location picker preserves the user's directory selection.

    The result is serialised with ``json.dumps()`` and rendered via
    ``|safe`` inside a ``<script>`` block, so every user-supplied
    string is passed through ``escape()`` to neutralise any embedded
    ``</script>`` sequences that would break out of the JSON island.
    """
    dir_path = post_data.get("directory_path", "").strip()
    if not dir_path:
        return []
    title_overrides = _parse_directory_titles(post_data)
    slugs = dir_path.strip("/").split("/")
    segments = []
    current_path = ""
    for slug in slugs:
        current_path = f"{current_path}/{slug}" if current_path else slug
        directory = Directory.objects.filter(path=current_path).first()
        if directory:
            title = directory.title
        elif current_path in title_overrides:
            title = title_overrides[current_path]
        else:
            title = slug.replace("-", " ").title()
        segments.append({"path": escape(current_path), "title": escape(title)})
    return segments


# Matches @username (word chars only, not followed by @)
_MENTION_RE = re.compile(r"@([a-zA-Z][a-zA-Z0-9._-]*)")


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


def _process_mentions_and_grants(page, request):
    """Extract @mentions from page content/change_message and process grants."""
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


def _resolve_or_create_directory(dir_path, user, title_overrides=None):
    """Resolve a directory path, creating missing segments as needed.

    New directories inherit visibility, editability, and permission
    grants from their parent directory.

    ``title_overrides`` is an optional dict mapping full segment paths
    to display titles (e.g. {"eng/api": "API"}).  When a new directory
    is created and its path appears in the mapping, the provided title
    is used instead of deriving one from the slug.
    """
    directory = Directory.objects.filter(path=dir_path).first()
    if directory:
        return directory

    if title_overrides is None:
        title_overrides = {}

    # Build each segment of the path, creating as needed
    segments = dir_path.strip("/").split("/")
    parent, _ = Directory.objects.get_or_create(
        path="", defaults={"title": "Home"}
    )
    current_path = ""

    with transaction.atomic():
        for segment in segments:
            current_path = (
                f"{current_path}/{segment}" if current_path else segment
            )
            title = title_overrides.get(
                current_path, segment.replace("-", " ").title()
            )
            directory, created = Directory.objects.get_or_create(
                path=current_path,
                defaults={
                    "title": title,
                    "parent": parent,
                    "owner": user,
                    "created_by": user,
                    "visibility": "inherit",
                    "editability": "inherit",
                    "in_sitemap": "inherit",
                    "in_llms_txt": "inherit",
                },
            )
            if created:
                # Copy permission grants from the parent directory
                parent_perms = DirectoryPermission.objects.filter(
                    directory=parent
                )
                for perm in parent_perms:
                    DirectoryPermission.objects.create(
                        directory=directory,
                        user=perm.user,
                        group=perm.group,
                        permission_type=perm.permission_type,
                    )
            parent = directory

    return directory


def _parse_directory_titles(post_data):
    """Parse the directory_titles JSON from POST data.

    Returns a dict mapping directory paths to user-provided titles
    for newly created directories, e.g. {"eng/api": "API"}.
    """
    raw = post_data.get("directory_titles", "").strip()
    if not raw:
        return {}
    try:
        titles = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(titles, dict):
        return {}
    return {k: v for k, v in titles.items() if isinstance(v, str) and v}


def resolve_path(request, path):
    """Unified catch-all: resolve a path as directory or page.

    1. Check if path matches a Directory → directory view
    2. Take last segment as slug, check Page → page view
    3. Check SlugRedirect → redirect
    4. 404
    """
    # Inline import to avoid circular dependency (directories/views imports pages/views)
    from wiki.directories.views import directory_detail

    clean_path = path.strip("/")

    # 1. Is it a directory?
    if Directory.objects.filter(path=clean_path).exists():
        return directory_detail(request, path)

    # 2. Try as a page (last segment = slug)
    slug = clean_path.split("/")[-1]

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
    slug = _parse_page_path(path)

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


def _build_page_breadcrumbs(request, page):
    """Build breadcrumbs for a page, hiding private ancestors."""
    breadcrumbs = [("Home", reverse("root"))]
    if page.directory:
        for ancestor in page.directory.get_ancestors():
            if not ancestor.path:
                continue  # skip root — already in breadcrumbs
            if not can_view_directory(request.user, ancestor):
                continue
            breadcrumbs.append((ancestor.title, ancestor.get_absolute_url()))
        if can_view_directory(request.user, page.directory):
            breadcrumbs.append(
                (page.directory.title, page.directory.get_absolute_url())
            )
    return breadcrumbs


def _render_page_detail(request, page):
    """Render the page detail view (shared by resolve_path and page_detail)."""
    if not can_view_page(request.user, page):
        raise Http404

    # Record page view tally
    PageViewTally.objects.create(page=page)

    content = page.content
    if page.data_source_url:
        data = fetch_page_data(page.data_source_url, page.data_source_ttl)
        content = substitute_data_variables(content, data)
    rendered_content = render_markdown(content)
    toc = getattr(rendered_content, "toc_html", "")

    breadcrumbs = _build_page_breadcrumbs(request, page)

    # Check subscription status and get watcher list
    is_subscribed = False
    watchers = []
    if request.user.is_authenticated:
        is_subscribed = is_effectively_subscribed_to_page(request.user, page)
        watchers = get_effective_watchers_for_page(page)

    people = _get_page_people(page)

    can_edit = can_edit_page(request.user, page)
    can_delete = request.user.is_authenticated and (
        page.owner == request.user or is_system_owner(request.user)
    )
    pending_proposal_count = 0
    pending_comment_count = 0
    if can_edit:
        pending_proposal_count = page.proposals.filter(
            status=ChangeProposal.Status.PENDING
        ).count()
        pending_comment_count = page.comments.filter(
            status=PageComment.Status.PENDING
        ).count()

    # SEO
    eff_visibility, _ = resolve_effective_value(page, "visibility")
    is_public = eff_visibility == "public"
    page_description = page.seo_description or extract_description(
        page.content
    )
    breadcrumbs_json = ""
    article_json = ""
    if is_public:
        breadcrumbs_json = build_breadcrumbs_jsonld(
            breadcrumbs, django_settings.BASE_URL
        )
        article_json = build_article_jsonld(
            page, page_description, django_settings.BASE_URL
        )
    else:
        request.seo_noindex = True

    canonical_url = f"{django_settings.BASE_URL}{page.get_absolute_url()}"
    request.seo_canonical = canonical_url

    return render(
        request,
        "pages/detail.html",
        {
            "page": page,
            "rendered_content": rendered_content,
            "toc": toc,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "pending_proposal_count": pending_proposal_count,
            "pending_comment_count": pending_comment_count,
            "breadcrumbs": breadcrumbs,
            "is_subscribed": is_subscribed,
            "watchers": watchers,
            "people": people,
            "is_public": is_public,
            "page_description": page_description,
            "breadcrumbs_json": breadcrumbs_json,
            "article_json": article_json,
            "canonical_url": canonical_url,
            "effective_visibility": eff_visibility,
        },
    )


@login_required
def page_create(request, path=""):
    """Create a new page, optionally within a directory."""
    directory = None
    if path:
        directory = get_object_or_404(Directory, path=path.strip("/"))

    # Check permissions on target directory
    if directory and directory.path:
        if not can_view_directory(request.user, directory):
            raise Http404
        if not can_edit_directory(request.user, directory):
            messages.error(
                request,
                "You don't have permission to create pages here.",
            )
            return redirect(directory.get_absolute_url())

    # Build breadcrumbs for the target directory
    breadcrumbs = [("Home", reverse("root"))]
    if directory:
        for ancestor in directory.get_ancestors():
            if not ancestor.path:
                continue
            breadcrumbs.append((ancestor.title, ancestor.get_absolute_url()))
        if directory.path:
            breadcrumbs.append((directory.title, directory.get_absolute_url()))
    breadcrumbs.append(("New Page", ""))

    # On POST, resolve the directory from the location picker so that
    # "inherit" is a valid choice when the user selected a directory.
    if request.method == "POST":
        form_directory = (
            _resolve_directory_from_post(request.POST) or directory
        )
    else:
        form_directory = directory

    form = PageForm(
        request.POST or None,
        directory=form_directory,
        initial={"change_message": "Add new page"},
    )
    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)

        # Use directory from location picker if provided
        dir_path = request.POST.get("directory_path", "").strip()
        if dir_path:
            title_overrides = _parse_directory_titles(request.POST)
            page.directory = _resolve_or_create_directory(
                dir_path, request.user, title_overrides
            )
        else:
            page.directory = directory

        page.owner = request.user
        page.created_by = request.user
        page.updated_by = request.user
        with transaction.atomic():
            page.save()
            _link_uploads_to_page(page, request.user)
            page.create_revision(
                request.user, page.change_message or "Initial creation"
            )
            PageSubscription.objects.get_or_create(
                user=request.user, page=page
            )

        _process_mentions_and_grants(page, request)

        messages.success(request, f'Page "{page.title}" created.')
        return redirect(page.get_absolute_url())

    return render(
        request,
        "pages/form.html",
        {
            "form": form,
            "directory": directory,
            "editing": False,
            "breadcrumbs": breadcrumbs,
            "dir_segments_json": json.dumps(
                _build_dir_segments_from_post(request.POST)
                if request.method == "POST"
                else _build_dir_segments(directory)
            ),
            "inherit_meta": getattr(form, "inherit_meta", {}),
        },
    )


@login_required
def page_edit(request, path):
    """Edit an existing page."""
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    if not can_edit_page(request.user, page):
        messages.error(request, "You don't have permission to edit this page.")
        return redirect(page.get_absolute_url())

    breadcrumbs = _build_page_breadcrumbs(request, page)

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

    # On POST, resolve the directory from the location picker so that
    # "inherit" is a valid choice when the user changed directories.
    if request.method == "POST":
        form_directory = (
            _resolve_directory_from_post(request.POST) or page.directory
        )
    else:
        form_directory = page.directory

    form = PageForm(
        request.POST or None,
        instance=page,
        editing=True,
        directory=form_directory,
    )
    if request.method != "POST":
        form.initial["change_message"] = ""
    if request.method == "POST" and form.is_valid():
        page = form.save(commit=False)
        page.updated_by = request.user

        # Handle directory change from location picker
        dir_path = request.POST.get("directory_path", "").strip()
        if dir_path:
            title_overrides = _parse_directory_titles(request.POST)
            page.directory = _resolve_or_create_directory(
                dir_path, request.user, title_overrides
            )
        else:
            page.directory = None

        with transaction.atomic():
            page.save()
            _link_uploads_to_page(page, request.user)
            if page.slug != old_slug:
                SlugRedirect.objects.update_or_create(
                    old_slug=old_slug,
                    defaults={"page": page},
                )
            rev = page.create_revision(request.user)
            PageSubscription.objects.get_or_create(
                user=request.user, page=page
            )

        notify_subscribers(
            page.id,
            request.user.id,
            page.change_message,
            prev_rev=rev.revision_number - 1
            if rev.revision_number > 1
            else None,
            new_rev=rev.revision_number,
        )
        _process_mentions_and_grants(page, request)

        release_lock_for_page(page)
        messages.success(request, f'Page "{page.title}" updated.')
        return redirect(page.get_absolute_url())

    return render(
        request,
        "pages/form.html",
        {
            "form": form,
            "page": page,
            "editing": True,
            "breadcrumbs": breadcrumbs,
            "dir_segments_json": json.dumps(
                _build_dir_segments_from_post(request.POST)
                if request.method == "POST"
                else _build_dir_segments(page.directory)
            ),
            "inherit_meta": getattr(form, "inherit_meta", {}),
        },
    )


@login_required
def page_move(request, path):
    """Move a page to a different directory."""
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    if not can_edit_page(request.user, page):
        messages.error(request, "You don't have permission to move this page.")
        return redirect(page.get_absolute_url())

    initial = {"directory": page.directory}
    form = PageMoveForm(
        request.POST or None,
        initial=initial,
        exclude_current=page.directory,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        new_directory = form.cleaned_data["directory"]

        if page_path_conflicts_with_directory(page.slug, new_directory):
            messages.error(
                request,
                "A directory already exists at that path. "
                "Rename the page or choose a different directory.",
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
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    if page.owner != request.user and not is_system_owner(request.user):
        messages.error(
            request, "You don't have permission to delete this page."
        )
        return redirect(page.get_absolute_url())

    all_incoming = list(
        page.incoming_links.select_related("from_page", "from_page__directory")
    )

    if request.method == "POST":
        if all_incoming:
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
        page.soft_delete(request.user)
        messages.success(request, f'Page "{title}" deleted.')
        return redirect(redirect_url)

    # Filter to only links the user can view (don't leak private titles)
    visible_links = [
        link
        for link in all_incoming
        if can_view_page(request.user, link.from_page)
    ]
    hidden_count = len(all_incoming) - len(visible_links)

    return render(
        request,
        "pages/delete_confirm.html",
        {
            "page": page,
            "incoming_links": visible_links,
            "hidden_link_count": hidden_count,
        },
    )


@login_required
def page_permissions(request, path):
    """Manage permissions for a page."""
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    if not can_edit_page(request.user, page):
        messages.error(
            request, "You don't have permission to manage this page."
        )
        return redirect(page.get_absolute_url())

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


def page_backlinks(request, path):
    """Show pages that link to this page."""
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    incoming_links = page.incoming_links.select_related(
        "from_page", "from_page__directory"
    ).order_by("from_page__title")

    # Filter out pages the current user can't view
    visible_links = [
        link
        for link in incoming_links
        if can_view_page(request.user, link.from_page)
    ]

    return render(
        request,
        "pages/backlinks.html",
        {"page": page, "incoming_links": visible_links},
    )


@login_required
def page_history(request, path):
    """Show revision history for a page."""
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    revisions = page.revisions.select_related("created_by").all()
    diff_base = reverse(
        "page_diff",
        kwargs={"path": page.content_path, "v1": 0, "v2": 0},
    ).rsplit("0/0/", 1)[0]
    return render(
        request,
        "pages/history.html",
        {"page": page, "revisions": revisions, "diff_base": diff_base},
    )


@login_required
def page_diff(request, path, v1, v2):
    """Show diff between two versions."""
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

    rev1 = get_object_or_404(PageRevision, page=page, revision_number=v1)
    rev2 = get_object_or_404(PageRevision, page=page, revision_number=v2)

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
    slug = _parse_page_path(path)
    page = get_object_or_404(Page, slug=slug)

    if not can_view_page(request.user, page):
        raise Http404

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
        with transaction.atomic():
            page.save()
            _link_uploads_to_page(page, request.user)
            rev = page.create_revision(request.user)

        notify_subscribers(
            page.id,
            request.user.id,
            page.change_message,
            prev_rev=rev.revision_number - 1
            if rev.revision_number > 1
            else None,
            new_rev=rev.revision_number,
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
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    page_slug = data.get("page_slug", "")
    usernames = data.get("usernames", [])
    linked_slugs = data.get("linked_slugs", [])

    # Check mentioned users
    users_without_access = []
    page = Page.objects.filter(slug=page_slug).first()

    page_eff_vis = None
    if page:
        page_eff_vis, _ = resolve_effective_value(page, "visibility")
    if page and page_eff_vis != "public":
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
    _openness = {"private": 0, "internal": 1, "public": 2}
    if linked_slugs and page:
        current_vis, _ = resolve_effective_value(page, "visibility")
        for slug in set(linked_slugs):
            if slug == page_slug:
                continue
            linked = Page.objects.filter(slug=slug).first()
            if not linked:
                continue
            linked_vis, _ = resolve_effective_value(linked, "visibility")
            # Flag if current page is more open than the linked page
            if _openness.get(current_vis, 0) > _openness.get(linked_vis, 0):
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
def page_preview_htmx(request):
    """Return rendered markdown preview for HTMX requests."""
    content = request.POST.get("content", "")
    rendered = render_markdown(content)
    return HttpResponse(rendered)


# SECURITY: block executable/script file types to prevent serving
# dangerous payloads even behind signed URLs.
BLOCKED_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".scr",
    ".pif",
    ".js",
    ".vbs",
    ".vbe",
    ".wsf",
    ".wsh",
    ".ps1",
    ".sh",
    ".bash",
    ".csh",
    ".dll",
    ".so",
    ".dylib",
    ".app",
    ".action",
    ".command",
    ".jar",
    ".class",
}


MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1 GB


@require_POST
@login_required
@ratelimit_upload
def file_upload_htmx(request):
    """Handle file upload via Django (dev mode, local FileSystemStorage)."""
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse({"error": "No file provided"}, status=400)

    ext = FilePath(uploaded_file.name).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        return JsonResponse(
            {"error": f"File type '{ext}' is not allowed."}, status=400
        )

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        return JsonResponse(
            {"error": "File too large. Maximum size is 1 GB."}, status=400
        )

    upload = FileUpload.objects.create(
        uploaded_by=request.user,
        file=uploaded_file,
        original_filename=uploaded_file.name,
        content_type=uploaded_file.content_type or "",
    )

    return JsonResponse({"markdown": _file_upload_markdown(upload)})


@require_POST
@login_required
@ratelimit_upload
def presign_upload(request):
    """Return a presigned S3 POST so the browser can upload directly."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    filename = body.get("filename", "")
    content_type = body.get("content_type", "") or "application/octet-stream"
    size = body.get("size", 0)

    if not filename:
        return JsonResponse({"error": "No filename provided"}, status=400)

    ext = FilePath(filename).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        return JsonResponse(
            {"error": f"File type '{ext}' is not allowed."}, status=400
        )

    if not size or size > MAX_UPLOAD_SIZE:
        return JsonResponse(
            {"error": "File too large. Maximum size is 1 GB."}, status=400
        )

    # Build S3 key: uploads/YYYY/MM/<uuid>_<sanitized_filename>
    now = datetime.now()
    safe_name = get_valid_filename(filename)
    s3_key = f"uploads/{now:%Y}/{now:%m}/{uuid.uuid4()}_{safe_name}"

    pending = PendingUpload.objects.create(
        s3_key=s3_key,
        original_filename=filename,
        content_type=content_type,
        expected_size=size,
        uploaded_by=request.user,
    )

    client = get_s3_client()
    presigned = client.generate_presigned_post(
        Bucket=django_settings.AWS_PRIVATE_STORAGE_BUCKET_NAME,
        Key=s3_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            ["content-length-range", 1, MAX_UPLOAD_SIZE],
            {"Content-Type": content_type},
        ],
        ExpiresIn=3600,  # 1 hour for large uploads on slow connections
    )

    return JsonResponse(
        {"presigned": presigned, "pending_id": str(pending.id)}
    )


@require_POST
@login_required
def confirm_upload(request):
    """Confirm a direct-to-S3 upload and create the FileUpload record."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    pending_id = body.get("pending_id", "")
    pending = get_object_or_404(
        PendingUpload, id=pending_id, uploaded_by=request.user
    )

    # Verify the object actually landed in S3
    client = get_s3_client()
    try:
        client.head_object(
            Bucket=django_settings.AWS_PRIVATE_STORAGE_BUCKET_NAME,
            Key=pending.s3_key,
        )
    except client.exceptions.ClientError:
        return JsonResponse(
            {"error": "File not found in storage. Upload may have failed."},
            status=400,
        )

    max_length = FileUpload._meta.get_field("file").max_length
    if len(pending.s3_key) > max_length:
        return JsonResponse(
            {
                "error": "Filename is too long. Please rename the file to something shorter and try again."
            },
            status=400,
        )

    upload = FileUpload(
        uploaded_by=request.user,
        original_filename=pending.original_filename,
        content_type=pending.content_type,
    )
    upload.file.name = pending.s3_key
    with transaction.atomic():
        upload.save()
        pending.delete()

    return JsonResponse({"markdown": _file_upload_markdown(upload)})


def _file_upload_markdown(upload):
    """Return markdown syntax for a FileUpload."""
    file_url = reverse(
        "file_serve",
        kwargs={
            "file_id": upload.id,
            "filename": upload.original_filename,
        },
    )
    if upload.content_type and upload.content_type.startswith("image/"):
        return f"![{upload.original_filename}]({file_url})"
    return f"[{upload.original_filename}]({file_url})"


def file_serve(request, file_id, filename):
    """Serve a file with permission checks. Redirect to signed S3 URL."""
    upload = get_object_or_404(FileUpload, id=file_id)

    # SECURITY: page-attached files require page-level view permission;
    # orphaned files (page=None) still require authentication so that
    # unauthenticated users cannot guess file IDs to access uploads.
    if upload.page:
        if not can_view_page(request.user, upload.page):
            raise Http404
    elif not request.user.is_authenticated:
        raise Http404

    # In development, serve directly; in production, redirect to S3
    if django_settings.DEBUG:
        return FileResponse(upload.file.open("rb"))

    # Generate a signed S3 URL and redirect
    url = upload.file.storage.url(upload.file.name)
    return redirect(url)


@login_required
@ratelimit_search
def page_search_htmx(request):
    """HTMX endpoint for page title autocomplete."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return HttpResponse("")

    # SECURITY: select_related("directory") needed for permission checks
    # that walk the directory tree. Without it each can_view_page() call
    # would trigger extra queries.
    qs = Page.objects.filter(title__icontains=q).select_related("directory")
    exclude_slug = request.GET.get("exclude", "").strip()
    if exclude_slug:
        qs = qs.exclude(slug=exclude_slug)

    # SECURITY: filter results by permission so private pages are never
    # revealed in autocomplete to users who lack access.
    results = []
    for p in qs.iterator():
        if can_view_page(request.user, p):
            results.append(p)
        if len(results) >= 10:
            break

    html = ""
    for p in results:
        # SECURITY: escape() prevents stored XSS via page titles/slugs.
        html += (
            f'<div class="px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700'
            f' cursor-pointer" data-slug="{escape(p.slug)}">'
            f"{escape(p.title)}</div>"
        )

    return HttpResponse(html)


@login_required
def recent_changes(request, username=None):
    """Show recent revisions across the wiki, optionally filtered by user."""
    if not request.user.is_staff:
        raise Http404

    short_name = username or request.GET.get("user")
    filter_user = None
    if short_name:
        filter_user = get_object_or_404(
            User, username=f"{short_name}@free.law"
        )

    visible_page_ids = Page.objects.filter(
        viewable_pages_q(request.user)
    ).values_list("pk", flat=True)

    revisions = (
        PageRevision.objects.filter(page_id__in=visible_page_ids)
        .select_related(
            "page",
            "page__directory",
            "created_by",
            "created_by__profile",
        )
        .order_by("-created_at")
    )

    if filter_user:
        revisions = revisions.filter(created_by=filter_user)

    paginator = Paginator(revisions, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "pages/recent_changes.html",
        {
            "page_obj": page_obj,
            "filter_user": filter_user,
        },
    )


@require_POST
@login_required
def toggle_pin(request, path):
    """Toggle the is_pinned flag on a page (requires directory edit)."""
    slug = _parse_page_path(path)
    page = get_object_or_404(
        Page.objects.select_related("directory"), slug=slug
    )

    directory = page.directory
    if not directory:
        directory = Directory.objects.filter(path="").first()
    if not directory or not can_edit_directory(request.user, directory):
        raise Http404

    page.is_pinned = not page.is_pinned
    page.save(update_fields=["is_pinned"])

    return JsonResponse({"is_pinned": page.is_pinned})


def page_raw_markdown(request, path):
    """Return raw markdown content for a page (respects permissions)."""
    slug = path.split("/")[-1]

    page = (
        Page.objects.filter(slug=slug)
        .select_related("directory", "owner")
        .first()
    )
    if not page:
        raise Http404

    if not can_view_page(request.user, page):
        raise Http404

    markdown = f"# {page.title}\n\n{page.content}"
    response = HttpResponse(markdown, content_type="text/markdown")
    response["Content-Disposition"] = f'inline; filename="{page.slug}.md"'
    canonical_url = f"{django_settings.BASE_URL}{page.get_absolute_url()}"
    response["X-Robots-Tag"] = "noindex"
    response["Link"] = f'<{canonical_url}>; rel="canonical"'
    return response
