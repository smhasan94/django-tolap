# Plan: E3 — Tool helper and DRF integration

**Source:** `docs/03-epics.md` E3; FR-15, FR-16. **Complexity:** Medium (4 stories).
**Depends on:** E2-S6 (`issue_context`).

## Requirements restatement

Give tool authors one decorator that resolves, signs, verifies and enforces, and give DRF
users viewset/serializer mixins that do the same for list/retrieve and refuse writes the
policy forbids. Both must coexist with upstream `tolap-mcp` wrappers.

## Patterns to mirror

| Category | Source | Pattern |
| --- | --- | --- |
| Per-call context | `tolap_mcp/wrapper.py` | Context passed per call, never stored on a shared instance |
| Denials | `SecureMcpToolWrapper.execute_with_enforcement` raises `PermissionError(f"Access denied: {reason}")` | `TolapDenied` message format identical |
| Write gating | `tolap_core.validate_write`, `write_operation_for_method` | Reuse for DRF methods |

## Files

```
django_tolap/tool.py        tolap_tool, tolap_context, ToolContext
django_tolap/drf.py         TolapViewSetMixin, TolapSerializerMixin (imports DRF lazily)
tests/test_tool.py, tests/test_tool_mcp_interop.py, tests/test_drf.py
```

## Interfaces

```python
@dataclass
class ToolContext:
    context: SecurityContext
    policy: EffectivePolicy
    def enforce(self, qs) -> list[dict]
    def deny(self, reason: str) -> NoReturn

def tolap_tool(source: str, *, identity: Callable[..., tuple[str, str]] | None = None, param: str = "tolap")
# wraps fn(*args, **kwargs): identity from kwargs user_id/tenant_id (popped) or identity(**kwargs)
# or settings TOLAP["IDENTITY"]; missing -> TolapDenied("identity not established")

@contextmanager
def tolap_context(user_id, tenant_id, source, *, context: SecurityContext | None = None) -> ToolContext

class TolapViewSetMixin:
    tolap_source: str
    def get_tolap_identity(self, request) -> tuple[str, str]   # (str(request.user.pk), TENANT_RESOLVER(request))
    def get_tolap_context(self) -> ToolContext
    def list(self, request): data = ctx.enforce(self.filter_queryset(self.get_queryset())); return Response(data)
    def retrieve(self, request, pk): rows = ctx.enforce(qs.filter(pk=pk)); 404 if not rows
    def initial(...)  # for POST/PUT/PATCH/DELETE: validate_write via upstream; 403 with reason
class TolapSerializerMixin:
    # get_fields() drops fields hidden by the view's policy; used for schema generation only
```

## Tasks

1. **E3-S1.** Implement `tool.py`; tests for kwarg identity, callable identity, settings
   identity, missing identity, externally supplied context (bypasses store), denial format.
2. **E3-S2.** Test-only dependency `tolap-mcp`; wrap `patients_search` with upstream
   `SecureMcpToolWrapper.execute_with_enforcement(context, "patients_search", fn, args,
   object_name="patients")` where `fn` uses `tolap_context(..., context=context)`; assert the
   result passes both layers and a hidden-field request is refused by upstream first.
3. **E3-S3.** `drf.py`; test app viewset; `TENANT_RESOLVER` default returns `"default"`.
4. **E3-S4.** Write refusal via upstream `validate_write(operation, object_name, fields,
   policy)`; schema: if `drf_spectacular` importable, hook `get_serializer` fields; else
   `TolapSerializerMixin.get_fields`.

## Validation

`make check`; `uv run pytest tests/test_tool_mcp_interop.py` with `tolap-mcp` installed.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| DRF pagination expects a QuerySet | High | Mixin paginates the enforced list with `paginate_queryset(list)`; documented limit interplay with `maxResults` |
| Identity source ambiguity | Medium | Explicit precedence: kwargs > `identity` arg > settings; tests |
| `tolap-mcp` 1.0.0 vs main signature drift | Low | Only `execute_with_enforcement`, stable in both |
