"""Django admin as the TOLAP policy authoring console."""

from __future__ import annotations

import json
from typing import Any

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from tolap_core import serialize

from django_tolap.audit import assignment_event, definition_event, record
from django_tolap.drift import drift_warnings_for_body
from django_tolap.forms import PolicyAssignmentForm, PolicyDefinitionForm, ResolvePreviewForm
from django_tolap.models import PolicyAssignment, PolicyAuditLog, PolicyDefinition
from django_tolap.store import DjangoPolicyStore


def _actor(request: HttpRequest) -> str | None:
    user = getattr(request, "user", None)
    return str(user.pk) if user is not None and user.is_authenticated else None


@admin.register(PolicyDefinition)
class PolicyDefinitionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    form = PolicyDefinitionForm
    list_display = ("name", "priority", "active", "description", "updated_at")
    list_filter = ("active",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")
    change_list_template = "admin/django_tolap/policydefinition/change_list.html"

    def save_model(
        self, request: HttpRequest, obj: PolicyDefinition, form: Any, change: bool
    ) -> None:
        super().save_model(request, obj, form, change)
        record(
            definition_event(obj.name, "updated" if change else "created", actor=_actor(request))
        )
        for warning in drift_warnings_for_body(obj.body):
            messages.warning(request, f"Schema drift: {warning}")

    def delete_model(self, request: HttpRequest, obj: PolicyDefinition) -> None:
        super().delete_model(request, obj)
        record(definition_event(obj.name, "deleted", actor=_actor(request)))

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        names = list(queryset.values_list("name", flat=True))
        super().delete_queryset(request, queryset)
        for name in names:
            record(definition_event(name, "deleted", actor=_actor(request)))

    def get_urls(self) -> list[Any]:
        custom = [
            path(
                "resolve-preview/",
                self.admin_site.admin_view(self.resolve_preview),
                name="django_tolap_resolve_preview",
            )
        ]
        return custom + super().get_urls()

    def resolve_preview(self, request: HttpRequest) -> HttpResponse:
        form = ResolvePreviewForm(request.POST or None)
        effective = None
        if request.method == "POST" and form.is_valid():
            store = DjangoPolicyStore(audit_to_db=False)
            try:
                policy = store.resolve_policy(
                    form.cleaned_data["user_id"],
                    form.cleaned_data["tenant_id"],
                    form.cleaned_data["source_connection_id"],
                )
            except Exception as exc:  # noqa: BLE001 - shown to the admin, not swallowed
                form.add_error(None, f"resolution failed: {exc!r}")
            else:
                effective = json.dumps(json.loads(serialize(policy)), indent=2)
        context = {**self.admin_site.each_context(request), "form": form, "effective": effective}
        return TemplateResponse(request, "admin/django_tolap/resolve_preview.html", context)


@admin.register(PolicyAssignment)
class PolicyAssignmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    form = PolicyAssignmentForm
    list_display = (
        "policy",
        "assignee_type",
        "assignee_identifier",
        "tenant_id",
        "source_connection_id",
        "active",
        "expires_at",
        "revoked_at",
    )
    list_filter = ("active", "assignee_type", "tenant_id")
    search_fields = ("policy__name", "assignee_identifier", "tenant_id", "source_connection_id")
    autocomplete_fields = ("policy",)

    def save_model(
        self, request: HttpRequest, obj: PolicyAssignment, form: Any, change: bool
    ) -> None:
        super().save_model(request, obj, form, change)
        record(
            assignment_event(
                str(obj.policy_id), obj.assignee_identifier, "saved", actor=_actor(request)
            )
        )

    def delete_model(self, request: HttpRequest, obj: PolicyAssignment) -> None:
        super().delete_model(request, obj)
        record(
            assignment_event(
                str(obj.policy_id), obj.assignee_identifier, "deleted", actor=_actor(request)
            )
        )

    def delete_queryset(self, request: HttpRequest, queryset: Any) -> None:
        keys = list(queryset.values_list("policy_id", "assignee_identifier"))
        super().delete_queryset(request, queryset)
        for policy_name, identifier in keys:
            record(assignment_event(str(policy_name), identifier, "deleted", actor=_actor(request)))


@admin.register(PolicyAuditLog)
class PolicyAuditLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("timestamp", "event_type", "policy_name", "assignee_identifier", "user_id")
    list_filter = ("event_type",)
    search_fields = ("policy_name", "assignee_identifier", "user_id", "details")
    readonly_fields = tuple(f.name for f in PolicyAuditLog._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
