from django import forms
from django.contrib.auth.models import Group
from django.utils.text import slugify

from wiki.lib.inheritance import resolve_effective_value
from wiki.lib.path_utils import directory_path_conflicts_with_page
from wiki.lib.permissions import can_view_directory

from .models import Directory, DirectoryPermission


class DirectoryMoveForm(forms.Form):
    parent = forms.ModelChoiceField(
        queryset=Directory.objects.all(),
        required=True,
        widget=forms.Select(attrs={"class": "input-text w-full"}),
        label="New parent directory",
    )

    def __init__(self, *args, directory=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Exclude the directory itself and its descendants
        excluded_ids = set()
        if directory:
            excluded_ids.add(directory.pk)
            self._collect_descendant_ids(directory, excluded_ids)
        qs = Directory.objects.exclude(pk__in=excluded_ids).order_by("path")
        # SECURITY: only show directories the user can view so that
        # private directory names are never leaked in the dropdown.
        if user:
            visible_pks = [d.pk for d in qs if can_view_directory(user, d)]
            qs = qs.filter(pk__in=visible_pks)
        self.fields["parent"].queryset = qs
        self.fields["parent"].label_from_instance = (
            lambda d: f"/{d.path}" if d.path else "/ (Root)"
        )

    @staticmethod
    def _collect_descendant_ids(directory, ids):
        for child in directory.children.all():
            ids.add(child.pk)
            DirectoryMoveForm._collect_descendant_ids(child, ids)


class DirectoryForm(forms.ModelForm):
    change_message = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "input-text w-full",
                "placeholder": "Briefly describe your changes...",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = Directory
        fields = [
            "title",
            "description",
            "visibility",
            "editability",
            "in_sitemap",
            "in_llms_txt",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "autocomplete": "off",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "input-text w-full",
                    "rows": 6,
                    "id": "markdown-editor",
                    "placeholder": "Markdown description...",
                }
            ),
            "visibility": forms.Select(attrs={"class": "input-text"}),
            "editability": forms.Select(attrs={"class": "input-text"}),
            "in_sitemap": forms.Select(attrs={"class": "input-text"}),
            "in_llms_txt": forms.Select(attrs={"class": "input-text"}),
        }

    def __init__(self, *args, is_root=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["editability"].required = False
        self.fields["in_llms_txt"].required = False
        self.fields["in_sitemap"].required = False

        if is_root:
            # Root directory: remove inherit option and discoverability fields
            self._remove_inherit_choices()
            del self.fields["in_sitemap"]
            del self.fields["in_llms_txt"]
        elif self.instance and self.instance.pk and self.instance.parent:
            self._add_inherit_choices(self.instance.parent)
        elif self.instance and self.instance.pk:
            # Non-root directory without a parent (shouldn't happen, but safe)
            self._remove_inherit_choices()

    def _add_inherit_choices(self, parent):
        """Build inherit metadata for each field."""
        field_configs = {
            "visibility": Directory.Visibility,
            "editability": Directory.Editability,
            "in_sitemap": Directory.SitemapStatus,
            "in_llms_txt": Directory.LlmsTxtStatus,
        }
        self.inherit_meta = {}
        for field_name, choices_class in field_configs.items():
            if field_name not in self.fields:
                continue
            eff_value, source = resolve_effective_value(parent, field_name)
            display = dict(choices_class.choices).get(eff_value, eff_value)
            explicit_choices = [
                c for c in choices_class.choices if c[0] != "inherit"
            ]
            self.fields[field_name].choices = [
                ("inherit", display)
            ] + explicit_choices
            self.inherit_meta[field_name] = {
                "value": eff_value,
                "display": display,
                "source": source.title,
            }

    def _remove_inherit_choices(self):
        """Remove 'inherit' from all field choices."""
        for field_name in (
            "visibility",
            "editability",
            "in_sitemap",
            "in_llms_txt",
        ):
            if field_name not in self.fields:
                continue
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


class DirectoryCreateForm(forms.ModelForm):
    class Meta:
        model = Directory
        fields = [
            "title",
            "description",
            "visibility",
            "editability",
            "in_sitemap",
            "in_llms_txt",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "autofocus": True,
                    "autocomplete": "off",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "input-text w-full",
                    "rows": 6,
                    "id": "markdown-editor",
                    "placeholder": "Markdown description (optional)...",
                }
            ),
            "visibility": forms.Select(attrs={"class": "input-text"}),
            "editability": forms.Select(attrs={"class": "input-text"}),
            "in_sitemap": forms.Select(attrs={"class": "input-text"}),
            "in_llms_txt": forms.Select(attrs={"class": "input-text"}),
        }

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent
        self.fields["editability"].required = False
        self.fields["in_llms_txt"].required = False
        self.fields["in_sitemap"].required = False

        if parent:
            self._add_inherit_choices(parent)
            # Default new directories to "inherit"
            for field_name in (
                "visibility",
                "editability",
                "in_sitemap",
                "in_llms_txt",
            ):
                self.initial.setdefault(field_name, "inherit")

    def _add_inherit_choices(self, parent):
        """Build inherit metadata for each field."""
        field_configs = {
            "visibility": Directory.Visibility,
            "editability": Directory.Editability,
            "in_sitemap": Directory.SitemapStatus,
            "in_llms_txt": Directory.LlmsTxtStatus,
        }
        self.inherit_meta = {}
        for field_name, choices_class in field_configs.items():
            eff_value, source = resolve_effective_value(parent, field_name)
            display = dict(choices_class.choices).get(eff_value, eff_value)
            explicit_choices = [
                c for c in choices_class.choices if c[0] != "inherit"
            ]
            self.fields[field_name].choices = [
                ("inherit", display)
            ] + explicit_choices
            self.inherit_meta[field_name] = {
                "value": eff_value,
                "display": display,
                "source": source.title,
            }

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

    def clean_title(self):
        title = self.cleaned_data["title"]
        slug = slugify(title)
        if not slug:
            raise forms.ValidationError("Title must produce a valid URL slug.")
        # Check for duplicate path under the same parent
        if self.parent and self.parent.path:
            full_path = f"{self.parent.path}/{slug}"
        else:
            full_path = slug
        if Directory.objects.filter(path=full_path).exists():
            raise forms.ValidationError(
                f'A directory named "{title}" already exists in this location.'
            )
        if directory_path_conflicts_with_page(full_path):
            raise forms.ValidationError(
                f'A page named "{title}" already exists at this path.'
            )
        return title

    def save(self, commit=True):
        directory = super().save(commit=False)
        # Set path from title (parent prefix is added by the view)
        directory.path = slugify(directory.title)
        if commit:
            directory.save()
        return directory


class DirectoryPermissionForm(forms.Form):
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
        choices=DirectoryPermission.PermissionType.choices,
        widget=forms.Select(attrs={"class": "input-text"}),
    )
