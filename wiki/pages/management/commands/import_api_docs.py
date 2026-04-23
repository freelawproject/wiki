"""Import CourtListener API docs from a wiki-exports directory.

Reads markdown files with YAML front matter, creates the directory tree,
downloads images, rewrites inter-page links, and creates/updates wiki
pages.  Idempotent — safe to run multiple times.

Each export file must have a ``wiki_path`` front matter field that
specifies the target path on the wiki (e.g., ``/c/api/rest/v4/``).
The script derives the directory structure and page slug from this path.

Usage (from docker/wiki/):

    docker compose exec wiki-django python manage.py import_api_docs /path/to/wiki-exports
    docker compose exec wiki-django python manage.py import_api_docs /path/to/wiki-exports --skip-images
    docker compose exec wiki-django python manage.py import_api_docs /path/to/wiki-exports --dry-run
"""

import mimetypes
import re
import urllib.request
from pathlib import Path

import yaml
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from wiki.directories.models import Directory
from wiki.pages.models import FileUpload, Page, PageRevision
from wiki.users.models import SystemConfig

SKIP_FILES = {"README.md", "LINK_MAP.md"}

# Words that should stay uppercase when generating directory titles.
UPPERCASE_WORDS = {"api", "rest"}

# Finds all courtlistener.com/static/ URLs in markdown content.
CL_STATIC_URL_RE = re.compile(
    r"https://www\.courtlistener\.com/static/[^\s\)\]\"\'>]+"
)

# Fields compared when deciding whether an existing page needs updating.
UPDATABLE_FIELDS = [
    "title",
    "content",
    "seo_description",
    "directory",
    "is_pinned",
    "visibility",
    "data_source_url",
    "data_source_ttl",
    "in_sitemap",
    "in_llms_txt",
]


# ---------------------------------------------------------------------------
# Parsing & link rewriting
# ---------------------------------------------------------------------------


def parse_front_matter(text):
    """Split YAML front matter from markdown body.

    Returns (metadata_dict, body_without_frontmatter).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    front_matter = text[3:end].strip()
    body = text[end + 4 :].strip()
    return yaml.safe_load(front_matter) or {}, body


def parse_wiki_path(wiki_path):
    """Extract (directory_path, slug) from a wiki_path like ``/c/api/rest/v4/``.

    Returns e.g. ``("api/rest", "v4")``.
    """
    # Strip /c/ prefix and trailing slash
    path = wiki_path.strip("/")
    if path.startswith("c/"):
        path = path[2:]
    parts = path.rsplit("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0]


def build_file_to_path_map(parsed_files):
    """Return {filename: wiki_url_path} built from wiki_path front matter."""
    mapping = {}
    for filename, (meta, _) in parsed_files.items():
        wiki_path = meta.get("wiki_path", "")
        if wiki_path:
            # Normalize: ensure it ends without trailing slash for links
            mapping[filename] = wiki_path.rstrip("/") + "/"
    return mapping


def _rewrite_target(target, file_to_path, image_map):
    """Rewrite a single link/image target if it matches a known file or image URL."""
    base, _, fragment = target.partition("#")
    anchor = f"#{fragment}" if fragment else ""

    if base in file_to_path:
        return file_to_path[base] + anchor
    if base in image_map:
        return image_map[base] + anchor
    return target


def rewrite_content_links(content, file_to_path, image_map):
    """Rewrite inter-page file refs and CL static image URLs in markdown."""

    # 1. Reference-style definitions:  [label]: target  or  [label]: url "title"
    def _ref(m):
        label, raw_target = m.group(1), m.group(2).strip()
        title_m = re.match(r'^(\S+)\s+"(.*)"$', raw_target)
        if title_m:
            url, title = title_m.group(1), title_m.group(2)
            return f'{label}: {_rewrite_target(url, file_to_path, image_map)} "{title}"'
        return (
            f"{label}: {_rewrite_target(raw_target, file_to_path, image_map)}"
        )

    content = re.sub(
        r"^(\[[^\]]+\]):\s*(.+)$", _ref, content, flags=re.MULTILINE
    )

    # 2. Inline links:  [text](target)  and  ![alt](target)
    def _inline(m):
        prefix, target = m.group(1), m.group(2)
        return f"{prefix}({_rewrite_target(target, file_to_path, image_map)})"

    content = re.sub(r"(!?\[[^\]]*\])\(([^)]+)\)", _inline, content)

    return content


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Import CourtListener API docs from a wiki-exports directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "source_dir",
            help="Path to the wiki-exports directory containing .md files.",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            help="Skip downloading images from CourtListener.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without writing to the database.",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"])
        if not source_dir.is_dir():
            raise CommandError(f"Source directory not found: {source_dir}")

        self.dry_run = options["dry_run"]
        self.skip_images = options["skip_images"]

        owner = self._get_owner()
        if not owner:
            return

        # 1. Parse all export files and collect image URLs
        parsed = {}  # filename → (metadata, body)
        image_urls = set()

        for filepath in sorted(source_dir.glob("*.md")):
            if filepath.name in SKIP_FILES:
                continue
            text = filepath.read_text(encoding="utf-8")
            meta, body = parse_front_matter(text)
            if not meta.get("wiki_path"):
                self.stderr.write(
                    self.style.WARNING(
                        f"Skipping {filepath.name}: no wiki_path"
                    )
                )
                continue
            parsed[filepath.name] = (meta, body)
            image_urls.update(CL_STATIC_URL_RE.findall(body))

        # 2. Build file→path map and determine needed directories
        file_to_path = build_file_to_path_map(parsed)
        dir_paths = set()
        for filename, (meta, _) in parsed.items():
            dir_path, _ = parse_wiki_path(meta["wiki_path"])
            if dir_path:
                dir_paths.add(dir_path)

        # 3. Create directory structure
        directories = self._ensure_directories(dir_paths, owner)

        # 4. Download images
        image_map = {}
        if not self.skip_images and image_urls:
            image_map = self._download_images(image_urls, owner)

        # 5. Create / update pages
        created = updated = unchanged = 0
        for filename, (meta, body) in parsed.items():
            dir_path, slug = parse_wiki_path(meta["wiki_path"])
            directory = directories.get(dir_path)
            content = rewrite_content_links(body, file_to_path, image_map)
            kwargs = self._page_kwargs(meta, content, slug, directory, owner)

            if self.dry_run:
                exists = Page.objects.filter(
                    directory=directory, slug=slug
                ).exists()
                verb = "update" if exists else "create"
                self.stdout.write(
                    f"  Would {verb}: {kwargs['title']} → {meta['wiki_path']}"
                )
                continue

            page, status = self._upsert_page(kwargs, owner)
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            else:
                unchanged += 1

        # 6. Attach orphaned images to pages
        if not self.dry_run and image_map:
            self._attach_images(image_map, parsed)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated, "
                f"{unchanged} unchanged."
            )
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_owner(self):
        """Return the system owner, first superuser, or first user."""
        config = SystemConfig.objects.first()
        if config:
            return config.owner
        user = User.objects.filter(is_superuser=True).first()
        if user:
            return user
        user = User.objects.first()
        if user:
            return user
        self.stderr.write(self.style.ERROR("No users — cannot import."))
        return None

    def _ensure_directories(self, dir_paths, owner):
        """Create all directories needed by the imported pages.

        Accepts a set of directory paths (e.g. ``{"api/rest", "api/rest/v3",
        "api/webhooks"}``).  Creates each path and all its ancestors.

        Returns ``{path_str: Directory}`` including the wiki root (``""``).
        """
        root, _ = Directory.objects.get_or_create(
            path="",
            defaults={
                "title": "Home",
                "owner": owner,
                "created_by": owner,
            },
        )
        dirs = {"": root}

        # Expand to include all ancestor paths
        all_paths = set()
        for dp in dir_paths:
            parts = dp.split("/")
            for i in range(len(parts)):
                all_paths.add("/".join(parts[: i + 1]))

        for dir_path in sorted(all_paths):
            if self.dry_run:
                self.stdout.write(f"  Would ensure dir: /{dir_path}/")
                dirs[dir_path] = None
                continue

            parts = dir_path.split("/")
            parent_path = "/".join(parts[:-1])
            parent = dirs[parent_path]
            words = parts[-1].replace("-", " ").split()
            title = " ".join(
                w.upper() if w.lower() in UPPERCASE_WORDS else w.title()
                for w in words
            )

            d, was_created = Directory.objects.get_or_create(
                path=dir_path,
                defaults={
                    "title": title,
                    "parent": parent,
                    "owner": owner,
                    "created_by": owner,
                    "visibility": Directory.Visibility.INHERIT,
                    "editability": Directory.Editability.INHERIT,
                    "in_sitemap": Directory.SitemapStatus.INHERIT,
                    "in_llms_txt": Directory.LlmsTxtStatus.INHERIT,
                },
            )
            if not was_created and d.title != title:
                d.title = title
                d.save(update_fields=["title"])
                self.stdout.write(f"  Renamed dir: /{dir_path}/ → {title}")
            dirs[dir_path] = d
            if was_created:
                self.stdout.write(f"  Created dir: /{dir_path}/")

        return dirs

    def _download_images(self, image_urls, owner):
        """Download CL static images, create FileUpload records.

        Returns ``{original_url: /files/<id>/<filename>}``.
        """
        mapping = {}
        for url in sorted(image_urls):
            filename = url.rsplit("/", 1)[-1]

            # Re-use if already downloaded in a previous run
            existing = FileUpload.objects.filter(
                original_filename=filename, uploaded_by=owner
            ).first()
            if existing:
                file_url = reverse(
                    "file_serve",
                    kwargs={"file_id": existing.pk, "filename": filename},
                )
                mapping[url] = file_url
                self.stdout.write(f"  Image reused: {filename}")
                continue

            if self.dry_run:
                mapping[url] = f"/files/TBD/{filename}"
                self.stdout.write(f"  Would download: {filename}")
                continue

            try:
                self.stdout.write(f"  Downloading: {filename} ...")
                req = urllib.request.Request(
                    url, headers={"User-Agent": "FLP-Wiki-Import/1.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                ct = mimetypes.guess_type(filename)[0] or "image/png"
                upload = FileUpload(
                    uploaded_by=owner,
                    original_filename=filename,
                    content_type=ct,
                )
                upload.file.save(filename, ContentFile(data), save=True)
                file_url = reverse(
                    "file_serve",
                    kwargs={"file_id": upload.pk, "filename": filename},
                )
                mapping[url] = file_url
                self.stdout.write(f"  Saved: {file_url}")
            except Exception as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"  Download failed ({filename}): {exc}"
                    )
                )
        return mapping

    def _page_kwargs(self, meta, content, slug, directory, owner):
        """Build a dict of Page field values from front matter + content."""
        kw = {
            "title": meta.get("title", slug),
            "slug": slug,
            "content": content,
            "directory": directory,
            "owner": owner,
            "visibility": Page.Visibility.INHERIT,
            "editability": Page.Editability.INHERIT,
            "in_sitemap": Page.SitemapStatus.INHERIT,
            "in_llms_txt": Page.LlmsTxtStatus.INHERIT,
            "is_pinned": False,
            "created_by": owner,
            "updated_by": owner,
        }
        if meta.get("description"):
            kw["seo_description"] = meta["description"][:300]
        if meta.get("data_source"):
            kw["data_source_url"] = meta["data_source"]
        if meta.get("data_source_cache"):
            kw["data_source_ttl"] = int(meta["data_source_cache"])
        if meta.get("search_engines") is False:
            kw["in_sitemap"] = Page.SitemapStatus.EXCLUDE
        if meta.get("ai_assistants") is False:
            kw["in_llms_txt"] = Page.LlmsTxtStatus.EXCLUDE
        return kw

    def _upsert_page(self, kwargs, owner):
        """Create or update a page.

        Returns ``(page, status)`` where status is
        ``"created"``, ``"updated"``, or ``"unchanged"``.
        """
        slug = kwargs["slug"]
        directory = kwargs.get("directory")
        existing = Page.objects.filter(directory=directory, slug=slug).first()

        if existing:
            return self._update_page(existing, kwargs, owner)

        # --- create -------------------------------------------------------
        with transaction.atomic():
            page = Page(**kwargs)
            page.change_message = "Imported from CourtListener"
            page.save()
            PageRevision.objects.create(
                page=page,
                title=page.title,
                content=page.content,
                change_message="Imported from CourtListener",
                revision_number=1,
                created_by=owner,
            )
        self.stdout.write(f"  Created: {page.title}")
        return page, "created"

    def _update_page(self, page, kwargs, owner):
        """Update an existing page if any tracked field differs.

        Uses ``QuerySet.update()`` to bypass ``Page.save()``'s slug
        regeneration logic, then manually refreshes the search vector
        and page-link graph.
        """
        changed = {}
        for field in UPDATABLE_FIELDS:
            if field not in kwargs:
                continue
            if getattr(page, field) != kwargs[field]:
                changed[field] = kwargs[field]

        if not changed:
            self.stdout.write(f"  Unchanged: {page.title}")
            return page, "unchanged"

        changed["change_message"] = "Updated by import_api_docs"
        changed["updated_by"] = owner
        changed["updated_at"] = timezone.now()
        with transaction.atomic():
            Page.objects.filter(pk=page.pk).update(**changed)
            page.refresh_from_db()
            page._update_search_vector()
            page._update_page_links()
            page.create_revision(owner, "Updated by import_api_docs")
        self.stdout.write(f"  Updated: {page.title}")
        return page, "updated"

    def _attach_images(self, image_map, parsed_files):
        """Attach orphaned FileUpload records to the first page that uses them."""
        for url, wiki_path in image_map.items():
            m = re.match(r"/files/(\d+)/", wiki_path)
            if not m:
                continue
            file_id = int(m.group(1))
            upload = FileUpload.objects.filter(
                pk=file_id, page__isnull=True
            ).first()
            if not upload:
                continue  # already attached

            for filename, (meta, body) in parsed_files.items():
                if url not in body:
                    continue
                dir_path, slug = parse_wiki_path(meta["wiki_path"])
                page = Page.objects.filter(
                    directory__path=dir_path, slug=slug
                ).first()
                if page:
                    upload.page = page
                    upload.save(update_fields=["page"])
                    break
