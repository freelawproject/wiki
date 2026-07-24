from django import forms

from .utils import normalize_subscriber_email


class EmailSubscribeForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(
            attrs={
                "class": "input-text w-full",
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }
        ),
    )
    # Honeypot — rendered off-screen; real users never see or fill it.
    website = forms.CharField(required=False)

    def clean_email(self):
        return normalize_subscriber_email(self.cleaned_data["email"])

    @property
    def is_spam(self):
        return bool(self.data.get("website"))
