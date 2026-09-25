# Plan: E2 — Django-model policy store, admin, contexts

**Source:** `docs/03-epics.md` E2; FR-3, FR-4, FR-5, FR-6, FR-11 (admin warnings).
**Complexity:** Medium (7 stories). **Depends on:** E1-S2 (conf), E1-S3 (fixtures).

## Requirements restatement

Store TOLAP policy definitions and assignments as Django models, expose them in Django admin
with validation and a resolve preview, implement upstream's `PolicyStore` protocol on top so
resolution is delegated to upstream `resolve`, log every mutation, and issue signed contexts.
The quickstart then needs no in-code policy.

## Patterns to mirror

| Category | Source | Pattern |
| --- | --- | --- |
| Store contract | `tolap_store/interfaces.py` (1.0.0) | Exact method set; `resolve_policy(user_id, tenant_id, source_connection_id)`; 1.1 adds keyword `declared_purpose=None` — accept and ignore it now so we conform to both |
| Store behavior | `tolap_store/in_memory_store.py` | `save_assignment` replaces on `(policy_name, assignee.identifier)`; audit event per mutation and per resolve; delegates to `tolap_core.resolve` |
| Audit | `tolap_store/audit.py` `PolicyAuditEvent` | Same field names in the model |
| Validation | `tolap_core.serialization.deserialize_policy_definition` | The only validator; no jsonschema dependency |
| Errors | E1 `exceptions.py` | `TolapDenied` for enforcement; `ValidationError` for admin |

## Files

```
django_tolap/models.py                 PolicyDefinition, PolicyAssignment, PolicyAuditLog
django_tolap/migrations/0001_initial.py
django_tolap/store.py                  DjangoPolicyStore
django_tolap/identity.py               DjangoGroupsIdentityResolver, load_identity_resolver()
django_tolap/registry.py               register(model, object_name=None); registered_models()
django_tolap/admin.py                  ModelAdmins, JSON widget, resolve-preview action
django_tolap/forms.py                  PolicyDefinitionForm (validates body, schema-drift warnings)
django_tolap/contexts.py               issue_context(), accept_context()
django_tolap/templates/django_tolap/resolve_preview.html
tests/test_models.py, test_store.py, test_store_conformance.py, test_admin.py,
tests/test_audit.py, test_contexts.py
```

## Interfaces

```python
class PolicyDefinition(models.Model):
    name = CharField(unique=True)            # mirrors body["name"]; kept in sync on save
    body = JSONField()                       # full upstream policy-definition JSON
    description, priority = ...              # denormalized from body for list display
    active = BooleanField(default=True)
    created_at, updated_at
    def to_upstream(self) -> tolap_core.PolicyDefinition   # deserialize_policy_definition(body)

class PolicyAssignment(models.Model):
    policy = FK(PolicyDefinition, to_field="name", on_delete=CASCADE)
    assignee_type = CharField(choices=AssigneeType values)
    assignee_identifier = CharField()
    tenant_id = CharField(null=True); source_connection_id = CharField(null=True)
    active = BooleanField(default=True); expires_at = DateTimeField(null=True)
    revoked_at = DateTimeField(null=True)
    granted_by, granted_at, reason           # upstream audit block, required
    class Meta: unique_together = (policy, assignee_type, assignee_identifier, tenant_id, source_connection_id)
    def to_upstream(self) -> tolap_core.PolicyAssignment

class PolicyAuditLog(models.Model):
    event_type, timestamp, details, user_id, policy_name, assignee_identifier

class DjangoPolicyStore:                      # satisfies tolap_store.PolicyStore
    def __init__(self, identity_resolver=None, on_audit=None)
    get_definition / list_definitions / save_definition / delete_definition
    get_assignments(user_id, tenant_id)       # SQL filter: active, not expired, not revoked, tenant match or null
    save_assignment / delete_assignment
    resolve_policy(user_id, tenant_id, source_connection_id, *, declared_purpose=None)
    # conveniences
    save_definition_json(body: dict) -> PolicyDefinition
    assign(policy_name, *, user_id=None, group=None, role=None, tenant_id=None, source=None, granted_by, reason, expires_at=None)

def issue_context(user_id, tenant_id, source, *, store=None, ttl=None) -> SecurityContext
def accept_context(serialized: str) -> SecurityContext      # upstream deserialize_context with settings key
```

`get_assignments` matching of group/role assignees: query all assignments for the tenant
whose assignee is the user, or a group/role in `identity_resolver.get_groups/get_roles(user_id)`.
This mirrors `InMemoryPolicyStore._assignment_matches_user` but in one query.

## Tasks

1. **E2-S1 models + migration.** Write models; `makemigrations`; add `makemigrations --check`
   to `make lint`. Validate: `tests/test_models.py` round-trips `to_upstream()` for every
   `fixtures/policies/*.json` and `fixtures/assignments/*.json`.
2. **E2-S2 store + identity.** Implement; mypy protocol test
   (`_: PolicyStore = DjangoPolicyStore()`); `DjangoGroupsIdentityResolver` uses
   `User.groups.values_list("name")`, roles `[]`. Validate: `tests/test_store.py`.
3. **E2-S3 conformance.** For each `fixtures/merge-scenarios/*.json`, load definitions and
   assignments into both `InMemoryPolicyStore` and `DjangoPolicyStore`, resolve, compare
   `serialize(effective)` bytes. Validate: `tests/test_store_conformance.py`.
4. **E2-S4 admin.** `PolicyDefinitionForm.clean_body` calls upstream deserializer and maps
   its exception to `ValidationError`; `clean` also computes drift warnings for every
   registered model whose object name the body targets and attaches them via
   `messages.warning` in `save_model`. Resolve preview: admin action on `PolicyAssignment`
   opens a form (user, tenant, source) and renders `serialize(effective)`. Validate:
   `tests/test_admin.py` with the admin client.
5. **E2-S5 audit.** Store writes `PolicyAuditLog`; `on_audit` callback optional; read-only
   admin. Validate: `tests/test_audit.py`.
6. **E2-S6 contexts.** `issue_context` = `store.resolve_policy` → `build_security_context
   (user, tenant, [policy], ttl)` → `sign_context(key)`. `accept_context` = upstream
   `deserialize_context(serialized, key)`. Validate: tamper/expiry tests reuse upstream's
   `fixtures/signing/*.json` known-answer to confirm we sign with the canonical form.
7. **E2-S7 README.** Replace in-code policy with admin/shell flow; update
   `scripts/quickstart_check.sh` to seed via `save_definition_json` + `assign`.

## Validation

`make check`; `DATABASE_URL=postgres://… make test`; `scripts/quickstart_check.sh`.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Group/role matching in SQL diverges from upstream in-memory semantics | Medium | E2-S3 conformance on merge fixtures plus a group/role assignment test; upstream `resolve` re-filters anyway |
| `to_field="name"` FK complicates renames | Low | Renames are edits to `body["name"]` blocked by form when assignments exist |
| Admin JSON editing is error-prone | Medium | Inline upstream error messages; drift warnings; resolve preview |
| Signing key in settings only | — | System check; never persisted |
