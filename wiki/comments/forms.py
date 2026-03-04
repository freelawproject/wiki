from django import forms

from .models import PageComment


class CommentForm(forms.ModelForm):
    class Meta:
        model = PageComment
        fields = ["message", "author_email"]
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "class": "input-text w-full",
                    "rows": 5,
                    "placeholder": "Leave your feedback or question...",
                }
            ),
            "author_email": forms.EmailInput(
                attrs={
                    "class": "input-text w-full",
                    "placeholder": "your@email.com (for notifications)",
                }
            ),
        }

    def __init__(self, *args, is_authenticated=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["message"].required = True
        if is_authenticated:
            del self.fields["author_email"]


class CommentReplyForm(forms.Form):
    reply = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "input-text w-full",
                "rows": 4,
                "placeholder": "Write your reply...",
            }
        ),
    )
