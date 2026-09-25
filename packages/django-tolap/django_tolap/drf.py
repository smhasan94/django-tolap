"""Django REST Framework integration: a viewset mixin and a serializer mixin.

``TolapViewSetMixin`` resolves the request user's policy for ``tolap_source`` once per
request, returns post-passed dicts from ``list``/``retrieve``, and gates unsafe methods with
upstream ``validate_write`` (the target row is fetched under the policy first, so an
update or delete of a row the user cannot see is refused as ``target row not permitted``).

``TolapSerializerMixin`` drops fields the policy hides, so generated schemas and any
serializer-based rendering agree with what ``enforce`` returns. With no caller identity
(an anonymous request, a public schema) there is no policy and the serializer is unchanged.

When ``drf-spectacular`` is installed the viewset mixin sets
:class:`~django_tolap.spectacular.TolapAutoSchema` as its ``schema``, so a schema generated
for an authenticated caller is that caller's view of the API.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

from django.db.models import Model
from django.utils.module_loading import import_string
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.schemas.inspectors import ViewInspector
from tolap_core import EffectivePolicy, WriteOperation, validate_write

from django_tolap.conf import settings
from django_tolap.contexts import issue_context
from django_tolap.enforce import validate
from django_tolap.exceptions import TolapDenied
from django_tolap.objects import object_name
from django_tolap.precheck import FieldRules, field_visible
from django_tolap.tool import IDENTITY_MISSING, ToolContext
from django_tolap.writes import HTTP_WRITE_OPERATIONS

HAS_SPECTACULAR = importlib.util.find_spec("drf_spectacular") is not None

WRITE_OPERATIONS = HTTP_WRITE_OPERATIONS


def _tenant_resolver() -> Callable[[Request], str]:
    path = settings.TENANT_RESOLVER
    if path is None:
        return lambda request: "default"
    resolver: Callable[[Request], str] = import_string(path)
    return resolver


def view_policy(view: Any) -> EffectivePolicy | None:
    """The policy a view resolves for its caller, or ``None`` when there is no caller.

    A ``TolapViewSetMixin`` view answers through ``tolap_policy_or_none``; any other view may
    expose a ``tolap_policy`` attribute.
    """
    resolve = getattr(view, "tolap_policy_or_none", None)
    if callable(resolve):
        policy: EffectivePolicy | None = resolve()
        return policy
    fallback: EffectivePolicy | None = getattr(view, "tolap_policy", None)
    return fallback


def view_model(view: Any) -> type[Model]:
    """The view's model, from ``queryset`` when set (safe under a mock request)."""
    queryset = getattr(view, "queryset", None)
    if queryset is not None:
        model: type[Model] = queryset.model
        return model
    resolved: type[Model] = view.get_queryset().model
    return resolved


def serializer_model(serializer: Any) -> type[Model] | None:
    """``Meta.model`` of a ``ModelSerializer``, else ``None``."""
    model: type[Model] | None = getattr(getattr(serializer, "Meta", None), "model", None)
    return model


def field_column(name: str, field: Any) -> str | None:
    """The model column a serializer field reads: its single-hop ``source``, else its name."""
    source: str | None = getattr(field, "source", None) or name
    if not source or source == "*" or "." in source:
        return None
    return source


class TolapSchema(ViewInspector):  # type: ignore[misc]
    """Descriptor handing out a fresh ``TolapAutoSchema`` per access, like DRF's default.

    A class-level inspector instance would be shared by every request; drf-spectacular binds
    the view onto it, so concurrent per-caller schema requests must not share one.
    """

    def __get__(self, instance: Any, owner: Any) -> Any:
        from django_tolap.spectacular import TolapAutoSchema

        inspector = TolapAutoSchema()
        inspector.view = instance
        return inspector


class TolapViewSetMixin:
    """Mix into a DRF ``GenericViewSet``/``ModelViewSet`` and set ``tolap_source``."""

    tolap_source: str = ""
    _tolap: ToolContext | None = None
    if HAS_SPECTACULAR:
        schema = TolapSchema()

    # -- identity and context --

    def get_tolap_identity(self, request: Request) -> tuple[str | None, str | None]:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None, None
        return str(user.pk), _tenant_resolver()(request)

    def get_tolap_context(self) -> ToolContext:
        if self._tolap is None:
            request: Request = self.request  # type: ignore[attr-defined]
            user_id, tenant_id = self.get_tolap_identity(request)
            if not user_id or not tenant_id:
                raise PermissionDenied(detail=f"Access denied: {IDENTITY_MISSING}")
            if not self.tolap_source:
                raise PermissionDenied(detail="Access denied: tolap_source is not configured")
            context = issue_context(user_id, tenant_id, self.tolap_source)
            validate(context)
            self._tolap = ToolContext(context=context, source=self.tolap_source)
        return self._tolap

    @property
    def tolap_policy(self) -> EffectivePolicy:
        return self.get_tolap_context().policy

    def tolap_policy_or_none(self) -> EffectivePolicy | None:
        """The caller's policy, or ``None`` when no identity is established.

        Anonymous requests and public schema generation have no caller to resolve a policy
        for; they are not refused here (``initial`` and ``enforce`` do that on real
        requests), they get no policy.
        """
        request: Request = self.request  # type: ignore[attr-defined]
        user_id, tenant_id = self.get_tolap_identity(request)
        if not user_id or not tenant_id:
            return None
        return self.tolap_policy

    # -- DRF hooks --

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)  # type: ignore[misc]
        self.get_tolap_context()
        operation = WRITE_OPERATIONS.get(request.method or "")
        if operation is not None:
            self.check_tolap_write(request, operation)

    def check_tolap_write(self, request: Request, operation: WriteOperation) -> None:
        queryset = self.get_queryset()  # type: ignore[attr-defined]
        payload: dict[str, Any] = {}
        if operation is not WriteOperation.delete:
            data = request.data
            # A QueryDict (form bodies) maps keys to lists; validate_write wants scalars.
            payload = data.dict() if hasattr(data, "dict") else dict(data)
        target_row: Any = None
        if operation is not WriteOperation.insert:
            rows = self._enforced(self._tolap_lookup(queryset))
            if not rows:
                raise PermissionDenied(detail="Access denied: target row not permitted")
            target_row = rows[0]
        result = validate_write(
            operation,
            object_name(queryset.model),
            payload,
            self.tolap_policy,
            target_row=target_row,
            full_replace=request.method == "PUT",
        )
        if not result.allowed:
            raise PermissionDenied(detail=f"Access denied: {result.reason}")

    def _tolap_lookup(self, queryset: Any) -> Any:
        """``queryset`` narrowed to the object the URL names (DRF's lookup conventions)."""
        lookup_field: str = getattr(self, "lookup_field", "pk")
        lookup_url_kwarg: str = getattr(self, "lookup_url_kwarg", None) or lookup_field
        value = self.kwargs.get(lookup_url_kwarg)  # type: ignore[attr-defined]
        return queryset.filter(**{lookup_field: value})

    def _enforced(self, queryset: Any) -> list[dict[str, Any]]:
        try:
            return self.get_tolap_context().enforce(queryset)
        except TolapDenied as exc:
            raise PermissionDenied(detail=str(exc)) from exc

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())  # type: ignore[attr-defined]
        rows = self._enforced(queryset)
        page = self.paginate_queryset(rows)  # type: ignore[attr-defined]
        if page is not None:
            return self.get_paginated_response(page)  # type: ignore[attr-defined]
        return Response(rows)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())  # type: ignore[attr-defined]
        rows = self._enforced(self._tolap_lookup(queryset))
        if not rows:
            raise NotFound()
        return Response(rows[0])


class TolapSerializerMixin:
    """Drop serializer fields the view's policy hides (needs ``view`` in the context)."""

    def get_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = super().get_fields()  # type: ignore[misc]
        view = self.context.get("view")  # type: ignore[attr-defined]
        policy = view_policy(view) if view is not None else None
        if policy is None:
            return fields
        model = serializer_model(self) or view_model(view)
        rules = FieldRules.of(policy)
        obj = object_name(model)
        concrete = {f.name for f in model._meta.concrete_fields}

        def visible(name: str, field: Any) -> bool:
            column = field_column(name, field)
            return column not in concrete or field_visible(rules, f"{obj}.{column}")

        return {name: field for name, field in fields.items() if visible(name, field)}
