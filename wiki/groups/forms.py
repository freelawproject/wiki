from django import forms


class GroupForm(forms.Form):
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "input-text w-full",
                "autocomplete": "off",
                "placeholder": "Group name",
            }
        ),
    )


class AddMemberForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(
            attrs={
                "class": "input-text w-full",
                "placeholder": "Type a username...",
                "autocomplete": "off",
                "id": "id_username",
            }
        ),
    )
