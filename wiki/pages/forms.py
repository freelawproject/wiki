from django import forms
from django.contrib.auth.models import Group

from wiki.directories.models import Directory
from wiki.lib.data_source import is_domain_allowed
from wiki.lib.inheritance import resolve_effective_value
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
            "seo_description",
            "in_sitemap",
            "in_llms_txt",
            "data_source_url",
            "data_source_ttl",
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
            "seo_description": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "placeholder": "Brief page summary for search engines...",
                    "autocomplete": "off",
                }
            ),
            "in_sitemap": forms.Select(attrs={"class": "input-text"}),
            "in_llms_txt": forms.Select(attrs={"class": "input-text"}),
            "data_source_url": forms.URLInput(
                attrs={
                    "class": "input-text w-full",
                    "placeholder": "https://api.example.com/data.json",
                    "autocomplete": "off",
                }
            ),
            "data_source_ttl": forms.NumberInput(
                attrs={
                    "class": "input-text w-24",
                    "min": "10",
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

    def __init__(self, *args, editing=False, directory=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["change_message"].required = True
        self.fields["change_message"].widget.attrs["required"] = True
        self.fields["editability"].required = False
        self.fields["in_llms_txt"].required = False
        self.fields["in_sitemap"].required = False
        self.fields["data_source_ttl"].required = False

        # Build inherit labels for each field
        if directory:
            self._add_inherit_choices(directory)
            # Default new pages to "inherit"
            if not editing and not self.instance.pk:
                for field_name in (
                    "visibility",
                    "editability",
                    "in_sitemap",
                    "in_llms_txt",
                ):
                    self.initial.setdefault(field_name, "inherit")
        else:
            # Root-level page: no directory to inherit from
            self._remove_inherit_choices()

    def _add_inherit_choices(self, directory):
        """Build inherit metadata for each field.

        Adds "inherit" as a valid choice and stores metadata about
        the resolved value and source for custom dropdown rendering.
        """
        field_configs = {
            "visibility": Page.Visibility,
            "editability": Page.Editability,
            "in_sitemap": Page.SitemapStatus,
            "in_llms_txt": Page.LlmsTxtStatus,
        }
        self.inherit_meta = {}
        for field_name, choices_class in field_configs.items():
            eff_value, source = resolve_effective_value(directory, field_name)
            display = dict(choices_class.choices).get(eff_value, eff_value)
            # Keep all explicit choices + inherit for validation
            explicit_choices = [
                c for c in choices_class.choices if c[0] != "inherit"
            ]
            self.fields[field_name].choices = [
                ("inherit", display)
            ] + explicit_choices
            # Store metadata for template rendering
            self.inherit_meta[field_name] = {
                "value": eff_value,
                "display": display,
                "source": source.title,
            }

    def _remove_inherit_choices(self):
        """Remove 'inherit' from all field choices (root-level pages)."""
        for field_name in (
            "visibility",
            "editability",
            "in_sitemap",
            "in_llms_txt",
        ):
            self.fields[field_name].choices = [
                c for c in self.fields[field_name].choices if c[0] != "inherit"
            ]

    def clean_editability(self):
        value = self.cleaned_data.get("editability")
        if value == "inherit":
            return value
        return value or "restricted"

    def clean_in_llms_txt(self):
        value = self.cleaned_data.get("in_llms_txt")
        if value == "inherit":
            return value
        return value or "exclude"

    def clean_in_sitemap(self):
        value = self.cleaned_data.get("in_sitemap")
        if value == "inherit":
            return value
        return value or "include"

    def clean_data_source_url(self):
        url = self.cleaned_data.get("data_source_url", "")
        if url and not is_domain_allowed(url):
            raise forms.ValidationError(
                "This domain is not in the allowed data source list."
            )
        return url

    def clean_data_source_ttl(self):
        return self.cleaned_data.get("data_source_ttl") or 300


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
