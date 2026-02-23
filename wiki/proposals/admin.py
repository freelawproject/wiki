from django.contrib import admin

from .models import ChangeProposal


@admin.register(ChangeProposal)
class ChangeProposalAdmin(admin.ModelAdmin):
    list_display = [
        "page",
        "proposed_by",
        "status",
        "change_message",
        "created_at",
        "reviewed_at",
    ]
    list_filter = ["status", "created_at", "reviewed_at"]
    search_fields = [
        "page__title",
        "proposed_by__email",
        "proposer_email",
        "change_message",
    ]
    raw_id_fields = ["page", "proposed_by", "reviewed_by"]
    date_hierarchy = "created_at"
    list_select_related = ["page", "proposed_by"]
