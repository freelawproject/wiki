from django import forms

from .models import ChangeProposal


class ProposalForm(forms.ModelForm):
    class Meta:
        model = ChangeProposal
        fields = [
            "proposed_title",
            "proposed_content",
            "change_message",
            "proposer_email",
        ]
        widgets = {
            "proposed_title": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "autocomplete": "off",
                }
            ),
            "proposed_content": forms.Textarea(
                attrs={
                    "class": "w-full",
                    "id": "markdown-editor",
                    "rows": 20,
                }
            ),
            "change_message": forms.TextInput(
                attrs={
                    "class": "input-text w-full",
                    "placeholder": "Describe your proposed changes...",
                    "autocomplete": "off",
                }
            ),
            "proposer_email": forms.EmailInput(
                attrs={
                    "class": "input-text w-full",
                    "placeholder": "your@email.com (for notifications)",
                }
            ),
        }

    def __init__(self, *args, is_authenticated=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["change_message"].required = True
        if is_authenticated:
            del self.fields["proposer_email"]
