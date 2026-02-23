from django import forms
from django.contrib.auth.models import Group
from django.utils.text import slugify

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
            }
        ),
    )

    class Meta:
        model = Directory
        fields = ["title", "description", "visibility", "editability"]
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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["editability"].required = False

    def clean_editability(self):
        return self.cleaned_data.get("editability") or "restricted"


class DirectoryCreateForm(forms.ModelForm):
    class Meta:
        model = Directory
        fields = ["title", "description", "visibility", "editability"]
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
        }

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent
        self.fields["editability"].required = False

    def clean_editability(self):
        return self.cleaned_data.get("editability") or "restricted"

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
