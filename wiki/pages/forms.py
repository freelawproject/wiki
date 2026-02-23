from django import forms
from django.contrib.auth.models import Group

from wiki.directories.models import Directory
from wiki.lib.permissions import can_view_directory

from .models import Page, PagePermission


class PageMoveForm(forms.Form):
    directory = forms.ModelChoiceField(
        queryset=Directory.objects.all(),
        required=False,
        empty_label="(Root — no directory)",
        widget=forms.Select(attrs={"class": "input-text w-full"}),
    )

    def __init__(self, *args, exclude_current=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Directory.objects.exclude(path="").order_by("path")
        if exclude_current:
            qs = qs.exclude(pk=exclude_current.pk)
        # SECURITY: only show directories the user can view so that
        # private directory names are never leaked in the dropdown.
        if user:
            visible_pks = [d.pk for d in qs if can_view_directory(user, d)]
            qs = qs.filter(pk__in=visible_pks)
        self.fields["directory"].queryset = qs
        self.fields["directory"].label_from_instance = lambda d: f"/{d.path}"


class PageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = [
            "title",
            "content",
            "visibility",
            "editability",
            "change_message",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "autocomplete": "off",
                }
            ),
            "content": forms.Textarea(
                attrs={
                    "class": "w-full",
                    "id": "markdown-editor",
                    "rows": 20,
                }
            ),
            "visibility": forms.Select(attrs={"class": "input-text"}),
            "editability": forms.Select(attrs={"class": "input-text"}),
            "change_message": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "placeholder": "Describe your changes...",
                    "autocomplete": "off",
                }
            ),
        }

    def __init__(self, *args, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["change_message"].required = True
        self.fields["change_message"].widget.attrs["required"] = True
        self.fields["editability"].required = False

    def clean_editability(self):
        return self.cleaned_data.get("editability") or "restricted"


class PagePermissionForm(forms.Form):
    username = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "input-text w-full",
                "placeholder": "Type a username...",
                "autocomplete": "off",
                "id": "id_username",
            }
        ),
    )
    group = forms.ModelChoiceField(
        queryset=Group.objects.all().order_by("name"),
        required=False,
        widget=forms.Select(attrs={"class": "input-text w-full"}),
    )
    permission_type = forms.ChoiceField(
        choices=PagePermission.PermissionType.choices,
        widget=forms.Select(attrs={"class": "input-text"}),
    )
