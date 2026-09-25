"""ORM write paths under a policy: ``enforce_save``, ``enforce_delete``, ``enforce_update``,
``enforce_queryset_delete``.

Every one runs upstream ``validate_write`` (permission and ``readOnly`` ceiling, object,
payload fields against hidden/read-only/allowed sets, row filters against the target row)
and fails closed: one unwritable field or one invisible target row refuses the whole write.
Target rows are read through :func:`~django_tolap.enforce.enforce`, so an update or delete
of a row the policy filters out is refused as ``target row not permitted`` rather than
silently skipped.

Nothing here returns data. A write that returns data is a read (spec section 4.5); read the
row back through ``enforce`` if the tool needs to show it.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model, QuerySet
from tolap_core import EffectivePolicy, SecurityContext, WriteOperation, validate_write

from django_tolap.enforce import enforce, validate
from django_tolap.exceptions import TolapDenied
from django_tolap.objects import object_name

TARGET_NOT_PERMITTED = "target row not permitted"


def _concrete_names(model: type[Model]) -> list[str]:
    return [f.attname for f in model._meta.concrete_fields]


def _attname(model: type[Model], name: str) -> str:
    """The column attribute for a field name (``patient`` -> ``patient_id``)."""
    field = model._meta.get_field(name)
    attname: str = getattr(field, "attname", name)
    return attname


def _payload(instance: Model, names: list[str]) -> dict[str, Any]:
    return {name: getattr(instance, name) for name in names}


def _insert_payload(instance: Model) -> dict[str, Any]:
    """The columns an insert names: every concrete field whose value is not the field's own
    default. A column left at its default (a hidden ``ssn`` the caller never touched, an
    unset auto primary key) is the database's to fill, not the caller's write."""
    payload: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        value = getattr(instance, field.attname)
        # ``get_default()`` is the declared default, else "" or None as Django would store.
        if value == field.get_default():
            continue
        payload[field.attname] = value
    return payload


def _check(
    operation: WriteOperation,
    model: type[Model],
    payload: dict[str, Any],
    policy: EffectivePolicy,
    *,
    target_row: Any = None,
    full_replace: bool = False,
) -> None:
    result = validate_write(
        operation,
        object_name(model),
        payload,
        policy,
        target_row=target_row,
        # Upstream validates every resource field when given the list; that is the full
        # replace rule, so the list goes only with one.
        resource_fields=_concrete_names(model) if full_replace else None,
        full_replace=full_replace,
    )
    if not result.allowed:
        raise TolapDenied(result.reason or "access denied")


def _visible_rows(queryset: QuerySet[Any], context: SecurityContext) -> list[dict[str, Any]]:
    """The rows the policy lets the caller see, or a denial if that is fewer than the query
    would touch: a bulk write must never silently skip rows."""
    rows = enforce(queryset, context)
    if len(rows) != queryset.count():
        raise TolapDenied(TARGET_NOT_PERMITTED)
    return rows


def enforce_save(
    instance: Model,
    context: SecurityContext,
    *,
    update_fields: list[str] | None = None,
    signing_key: str | None = None,
) -> None:
    """``instance.save()`` under the policy: an insert when the instance is new, otherwise an
    update of the row it names, which must be visible.

    A save without ``update_fields`` overwrites every column, so it is validated as a full
    replace: a ``readOnlyFields`` column is protected even when the caller did not touch it.
    """
    validate(context, signing_key=signing_key)
    policy = context.effective_policy
    model = type(instance)
    names = _concrete_names(model)
    if instance._state.adding or instance.pk is None:
        _check(WriteOperation.insert, model, _insert_payload(instance), policy)
        instance.save()
        return
    if update_fields is not None:
        attnames = [_attname(model, f) for f in update_fields]
        payload = _payload(instance, attnames)
        full_replace = False
    else:
        payload = _payload(instance, names)
        full_replace = True
    rows = enforce(model._default_manager.filter(pk=instance.pk), context, signing_key=signing_key)
    if not rows:
        raise TolapDenied(TARGET_NOT_PERMITTED)
    _check(
        WriteOperation.update, model, payload, policy, target_row=rows[0], full_replace=full_replace
    )
    instance.save(update_fields=update_fields)


def enforce_delete(
    instance: Model, context: SecurityContext, *, signing_key: str | None = None
) -> None:
    """``instance.delete()`` under the policy; the row must be visible and deletable."""
    validate(context, signing_key=signing_key)
    model = type(instance)
    rows = enforce(model._default_manager.filter(pk=instance.pk), context, signing_key=signing_key)
    if not rows:
        raise TolapDenied(TARGET_NOT_PERMITTED)
    _check(WriteOperation.delete, model, {}, context.effective_policy, target_row=rows[0])
    instance.delete()


def enforce_update(
    queryset: QuerySet[Any],
    context: SecurityContext,
    *,
    signing_key: str | None = None,
    **values: Any,
) -> int:
    """``queryset.update(**values)`` under the policy. Refused as a whole if the QuerySet would
    touch a row the policy filters out, or if any target row fails ``validate_write``.
    Returns the number of rows updated."""
    validate(context, signing_key=signing_key)
    policy = context.effective_policy
    model = queryset.model
    payload = {_attname(model, k): v for k, v in values.items()}
    for row in _visible_rows(queryset, context):
        _check(WriteOperation.update, model, payload, policy, target_row=row)
    updated: int = queryset.update(**values)
    return updated


def enforce_queryset_delete(
    queryset: QuerySet[Any], context: SecurityContext, *, signing_key: str | None = None
) -> int:
    """``queryset.delete()`` under the policy, with the same all-or-nothing rule as
    :func:`enforce_update`. Returns the number of objects deleted."""
    validate(context, signing_key=signing_key)
    policy = context.effective_policy
    model = queryset.model
    for row in _visible_rows(queryset, context):
        _check(WriteOperation.delete, model, {}, policy, target_row=row)
    deleted, _ = queryset.delete()
    return int(deleted)
