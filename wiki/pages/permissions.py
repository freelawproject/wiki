"""Re-export from wiki.lib.permissions for convenience."""

from wiki.lib.permissions import (
    can_edit_page,
    can_view_page,
    is_system_owner,
)

__all__ = ["can_view_page", "can_edit_page", "is_system_owner"]
