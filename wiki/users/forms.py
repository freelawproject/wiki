from django import forms


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={
                "placeholder": "you@free.law",
                "class": "input-text w-full",
                "autofocus": True,
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if not email.endswith("@free.law"):
            raise forms.ValidationError(
                "Only @free.law email addresses are allowed."
            )
        return email


class UserSettingsForm(forms.Form):
    display_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input-text w-full"}),
    )
