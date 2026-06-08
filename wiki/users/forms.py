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
        return self.cleaned_data["email"].strip().lower()
