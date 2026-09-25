"""drf-spectacular schema generation for ``TolapViewSetMixin`` views.

``TolapViewSetMixin`` binds a :class:`TolapAutoSchema` when ``drf-spectacular`` is
importable. A schema generated with no caller (``manage.py spectacular``, an anonymous
request) documents the whole serializer and every method. A schema generated for an
authenticated caller is that caller's view of the API, whether or not ``SERVE_PUBLIC`` is
set (drf-spectacular hands the caller to the view either way; ``SERVE_PUBLIC`` only decides
whether DRF permission checks filter endpoints):

- an object the caller's policy cannot query, or whose model the view cannot name, has no
  operations at all;
- write methods the policy refuses (``readOnly``, missing ``canInsert``/``canUpdate``/
  ``canDelete``) are absent;
- hidden fields are absent (``TolapSerializerMixin``) and masked fields carry
  ``x-tolap-mask`` with the mask type, keyed by the column a field reads (its ``source``)
  and the model of the serializer that owns it.

Every operation on a TOLAP view names its source in ``x-tolap-source`` and in the
description. Do not cache a schema generated for one caller and serve it to another.

To combine with your own ``AutoSchema`` subclass, subclass :class:`TolapAutoSchema` and set
it as ``schema`` on the viewset.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import get_view_model
from tolap_core import EffectivePolicy, validate_access, validate_write

from django_tolap.drf import field_column, serializer_model, view_policy
from django_tolap.matching import field_matches
from django_tolap.objects import object_name
from django_tolap.writes import HTTP_WRITE_OPERATIONS, WRITE_TARGET_UNVERIFIABLE

SOURCE_NOTE = (
    "Enforced by TOLAP for source `{source}`: rows, fields, masking and the result limit "
    "follow the caller's effective policy."
)


class TolapAutoSchema(AutoSchema):
    """drf-spectacular ``AutoSchema`` that documents what the caller's policy allows."""

    _policy_resolved: bool = False
    _policy: EffectivePolicy | None = None

    # -- what the view tells us --

    def _tolap_source(self) -> str:
        source: str = getattr(self.view, "tolap_source", "") or ""
        return source

    def _tolap_policy(self) -> EffectivePolicy | None:
        """The caller's policy, resolved once per bound schema; ``None`` without a caller."""
        if not self._policy_resolved:
            self._policy = view_policy(self.view) if self._tolap_source() else None
            self._policy_resolved = True
        return self._policy

    # -- operations --

    def is_excluded(self) -> bool:
        return super().is_excluded() or self._tolap_refuses(self.method)

    def _tolap_refuses(self, method: str) -> bool:
        """Whether the caller's policy refuses this method on the view's object outright."""
        policy = self._tolap_policy()
        if policy is None:
            return False
        model = get_view_model(self.view)  # type: ignore[no-untyped-call]
        if model is None:
            return True  # the object cannot be named, so nothing can be documented
        obj = object_name(model)
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
        """The mask type the caller's policy applies to the column this field reads, if any.

        The column belongs to the model of the serializer that owns the field, so a nested
        ``ModelSerializer`` is annotated under its own object's rules; a field of a plain
        ``Serializer`` reads no known column and is left alone.
        """
        policy = self._tolap_policy()
        if policy is None or policy.object_rules is None or policy.object_rules.field_rules is None:
            return None
        model = serializer_model(getattr(field, "parent", None))
        name = getattr(field, "field_name", None)
        if model is None or not name:
            return None
        column = field_column(name, field)
        if column not in {f.name for f in model._meta.concrete_fields}:
            return None
        key = f"{object_name(model)}.{column}"
        for rule in policy.object_rules.field_rules.masked_fields or ():
            if field_matches(rule.field, key):
                mask_type: str = rule.mask_type.value
                return mask_type
        return None
