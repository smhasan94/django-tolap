"""drf-spectacular schema generation for ``TolapViewSetMixin`` views.

``TolapViewSetMixin`` uses :class:`TolapAutoSchema` automatically when ``drf-spectacular``
is importable. A public schema (``SERVE_PUBLIC = True``, the default) has no caller, so it
documents the whole serializer and every method. A schema served to an authenticated caller
(``SERVE_PUBLIC = False``) is that caller's view of the API:

- an object the caller's policy cannot query has no operations at all;
- write methods the policy refuses (``readOnly``, missing ``canInsert``/``canUpdate``/
  ``canDelete``) are absent;
- hidden fields are absent (``TolapSerializerMixin``) and masked fields carry
  ``x-tolap-mask`` with the mask type.

Every operation on a TOLAP view names its source in ``x-tolap-source`` and in the
description, in both kinds of schema.

To combine with your own ``AutoSchema`` subclass, subclass :class:`TolapAutoSchema` and set
it as ``schema`` on the viewset.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.openapi import AutoSchema
from tolap_core import EffectivePolicy, validate_access, validate_write

from django_tolap.matching import field_matches
from django_tolap.objects import object_name
from django_tolap.writes import HTTP_WRITE_OPERATIONS

WRITE_TARGET_UNVERIFIABLE = "write target unverifiable"
SOURCE_NOTE = (
    "Enforced by TOLAP for source `{source}`: rows, fields, masking and the result limit "
    "follow the caller's effective policy."
)


class TolapAutoSchema(AutoSchema):
    """drf-spectacular ``AutoSchema`` that documents what the caller's policy allows."""

    # -- what the view tells us --

    def _tolap_source(self) -> str:
        source: str = getattr(self.view, "tolap_source", "") or ""
        return source

    def _tolap_policy(self) -> EffectivePolicy | None:
        """The caller's policy, or ``None`` for a public schema or a non-TOLAP view."""
        if not self._tolap_source():
            return None
        resolve = getattr(self.view, "tolap_policy_or_none", None)
        policy: EffectivePolicy | None = resolve() if callable(resolve) else None
        return policy

    def _tolap_object(self) -> str:
        return object_name(self.view.get_queryset().model)

    # -- operations --

    def get_operation(
        self, path: str, path_regex: str, path_prefix: str, method: str, registry: Any
    ) -> dict[str, Any] | None:
        if self._tolap_refuses(method):
            return None
        operation: dict[str, Any] | None = super().get_operation(
            path, path_regex, path_prefix, method, registry
        )
        return operation

    def _tolap_refuses(self, method: str) -> bool:
        """Whether the caller's policy refuses this method on the view's object outright."""
        policy = self._tolap_policy()
        if policy is None:
            return False
        obj = self._tolap_object()
        if not validate_access(obj, policy).allowed:
            return True
        operation = HTTP_WRITE_OPERATIONS.get(method.upper())
        if operation is None:
            return False
        # Empty payload, no target row: this exercises the permission ceiling and the object
        # rules. Row filters make the target unverifiable at schema time, which is not a
        # refusal of the method; the request itself is checked against the real row.
        result = validate_write(operation, obj, {}, policy)
        return not (result.allowed or result.reason == WRITE_TARGET_UNVERIFIABLE)

    def get_description(self) -> str:
        description: str = super().get_description()
        source = self._tolap_source()
        if not source:
            return description
        note = SOURCE_NOTE.format(source=source)
        return f"{description}\n\n{note}" if description else note

    def get_extensions(self) -> dict[str, Any]:
        extensions: dict[str, Any] = dict(super().get_extensions())
        source = self._tolap_source()
        if source:
            extensions["x-tolap-source"] = source
        return extensions

    # -- fields --

    def _map_serializer_field(
        self, field: Any, direction: str, bypass_extensions: bool = False
    ) -> dict[str, Any] | None:
        schema: dict[str, Any] | None = super()._map_serializer_field(  # type: ignore[no-untyped-call]
            field, direction, bypass_extensions
        )
        mask = self._tolap_mask(field)
        if schema is None or mask is None:
            return schema
        return {**schema, "x-tolap-mask": mask}

    def _tolap_mask(self, field: Any) -> str | None:
        """The mask type the caller's policy applies to this concrete model field, if any."""
        policy = self._tolap_policy()
        if policy is None or policy.object_rules is None or policy.object_rules.field_rules is None:
            return None
        model = self.view.get_queryset().model
        name = getattr(field, "field_name", None)
        if name not in {f.name for f in model._meta.concrete_fields}:
            return None
        key = f"{object_name(model)}.{name}"
        for rule in policy.object_rules.field_rules.masked_fields or ():
            if field_matches(rule.field, key):
                mask_type: str = rule.mask_type.value
                return mask_type
        return None
