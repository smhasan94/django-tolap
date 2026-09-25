from __future__ import annotations

from typing import Any

from django import forms

from django_tolap.models import PolicyAssignment, PolicyDefinition


class PolicyDefinitionForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = PolicyDefinition
        fields = ["name", "body", "active"]
        widgets = {"body": forms.Textarea(attrs={"rows": 28, "cols": 100, "spellcheck": "false"})}
        help_texts = {"name": "Must equal body['name']. Leave blank to take it from the body."}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False


class PolicyAssignmentForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = PolicyAssignment
        fields = "__all__"


class ResolvePreviewForm(forms.Form):
    user_id = forms.CharField()
    tenant_id = forms.CharField()
    source_connection_id = forms.CharField(
        initial="db:", help_text="category:namespace:name, e.g. db:clinic:patients"
    )
