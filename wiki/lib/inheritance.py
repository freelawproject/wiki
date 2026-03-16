"""Inheritance resolution for page and directory settings.

All four settings (visibility, editability, in_sitemap, in_llms_txt) use the
same inheritance model:
- "inherit" means resolve from the nearest ancestor with an explicit value
- Any other value is explicit and takes effect directly

The root directory (path="") always has explicit values and acts as the
termination point for inheritance resolution.
"""

import logging

from wiki.directories.models import Directory

logger = logging.getLogger(__name__)

# Model-level defaults used as fallbacks when resolution fails
_FIELD_DEFAULTS = {
    "visibility": "public",
    "editability": "restricted",
    "in_sitemap": "include",
    "in_llms_txt": "exclude",
}

INHERITABLE_FIELDS = ("visibility", "editability", "in_sitemap", "in_llms_txt")


def resolve_effective_value(obj, field_name):
    """Return (effective_value, source_obj) for a Page or Directory.

    Walks: page → directory → directory.parent → ... → root.
    Stops at the first non-"inherit" value.
    """
    from wiki.pages.models import Page

    if isinstance(obj, Page):
        value = getattr(obj, field_name)
        if value != "inherit":
            return value, obj
        # Walk the directory chain
        directory = obj.directory
        if directory is None:
            logger.warning(
                "Page %s has '%s=inherit' but no directory; "
                "falling back to default",
                obj.pk,
                field_name,
            )
            return _FIELD_DEFAULTS[field_name], obj
        return _resolve_directory_value(directory, field_name)

    if isinstance(obj, Directory):
        return _resolve_directory_value(obj, field_name)

    raise TypeError(f"Expected Page or Directory, got {type(obj)}")


def _resolve_directory_value(directory, field_name):
    """Walk directory → parent → ... → root to find first explicit value."""
    current = directory
    while current is not None:
        value = getattr(current, field_name)
        if value != "inherit":
            return value, current
        current = current.parent

    # Should never happen — root always has explicit values
    logger.warning(
        "Reached end of directory chain without finding explicit '%s'; "
        "falling back to default",
        field_name,
    )
    return _FIELD_DEFAULTS[field_name], directory


def resolve_all_directory_settings(field_name):
    """Bulk resolve all directories for a single field.

    Returns {dir_id: (effective_value, source_dir_id, source_dir_title)}.

    Loads all directories in one query, builds a parent map, and resolves
    each directory's effective value by walking its ancestor chain in memory.
    """
    dir_data = {}  # pk -> (parent_id, field_value, title, path)
    for d in Directory.objects.only(
        "pk", "parent_id", field_name, "title", "path"
    ).iterator():
        dir_data[d.pk] = (d.parent_id, getattr(d, field_name), d.title, d.path)

    result = {}
    # Cache resolved values to avoid re-walking shared ancestors
    resolved_cache = {}  # pk -> (effective_value, source_pk, source_title)

    for dir_id in dir_data:
        _resolve_cached(dir_id, field_name, dir_data, resolved_cache)

    result = dict(resolved_cache)
    return result


def _resolve_cached(dir_id, field_name, dir_data, cache):
    """Recursively resolve with memoization."""
    if dir_id in cache:
        return cache[dir_id]

    parent_id, value, title, path = dir_data[dir_id]

    if value != "inherit":
        cache[dir_id] = (value, dir_id, title)
        return cache[dir_id]

    # Inherit from parent
    if parent_id is None or parent_id not in dir_data:
        # Root or orphan — fall back to default
        default = _FIELD_DEFAULTS[field_name]
        cache[dir_id] = (default, dir_id, title)
        return cache[dir_id]

    parent_result = _resolve_cached(parent_id, field_name, dir_data, cache)
    cache[dir_id] = parent_result
    return parent_result
