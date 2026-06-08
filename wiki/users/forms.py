import re

from django import forms

from wiki.lib.access import is_email_allowed
from wiki.users.models import AllowedDomain


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "placeholder": "you@example.com",
                "class": "input-text w-full",
                "autofocus": True,
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if not is_email_allowed(email):
            raise forms.ValidationError(
                "That email address isn't allowed to sign in. "
                "Contact an admin if you need access."
            )
        return email


class UserSettingsForm(forms.Form):
    display_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input-text w-full"}),
    )


class AllowedDomainForm(forms.Form):
    domain = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"placeholder": "example.com", "class": "input-text w-full"}
        ),
    )
    suffix = forms.CharField(
        max_length=32,
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. acme", "class": "input-text w-full"}
        ),
    )
    note = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Optional note",
                "class": "input-text w-full",
            }
        ),
    )

    def clean_domain(self):
        domain = AllowedDomain.normalize(self.cleaned_data["domain"])
        if not domain or "." not in domain or "@" in domain or " " in domain:
            raise forms.ValidationError(
                "Enter a valid domain, e.g. example.com."
            )
        return domain

    def clean_suffix(self):
        suffix = AllowedDomain.normalize_suffix(self.cleaned_data["suffix"])
        if not re.fullmatch(r"[a-z0-9]+", suffix):
            raise forms.ValidationError(
                "Suffix must be letters and numbers only, e.g. acme."
            )
        if AllowedDomain.objects.filter(suffix=suffix).exists():
            raise forms.ValidationError(
                f'The suffix "{suffix}" is already used by another domain.'
            )
        return suffix


class AllowedEmailForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "placeholder": "person@example.com",
                "class": "input-text w-full",
            }
        ),
    )
    note = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Optional note",
                "class": "input-text w-full",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Plus-addressing is blocked at sign-in, so an allowlisted plus
        # address would never resolve — reject it on entry to avoid a
        # dead allowlist row.
        local = email.split("@", 1)[0]
        if "+" in local:
            raise forms.ValidationError(
                "Plus-addressing (e.g. you+tag@example.com) isn't allowed; "
                "use the base address instead."
            )
        return email
