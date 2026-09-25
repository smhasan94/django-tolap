"""``manage.py tolap_resolve``: what a user resolves to, from the shell.

The same resolution the admin's "Resolve preview" runs (upstream ``resolve`` over the store's
assignments and definitions), printed as JSON so it can be piped. Nothing is audited unless
``--audit`` is given; a preview is not a grant.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from tolap_core import serialize

from django_tolap.contexts import issue_context
from django_tolap.contexts import serialize as serialize_context
from django_tolap.store import DjangoPolicyStore


class Command(BaseCommand):
    help = "Print the effective TOLAP policy a user resolves to (JSON), or a signed context."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("user_id")
        parser.add_argument("--tenant", default="default", help="tenant id (default: 'default')")
        parser.add_argument(
            "--source", default="", help="source connection id the tool will read (default: '')"
        )
        parser.add_argument(
            "--assignments",
            action="store_true",
            help="also list the assignments considered, as {'assignments': [...], 'policy': {...}}",
        )
        parser.add_argument(
            "--context",
            action="store_true",
            help="print a signed, serialized SecurityContext instead of the policy JSON",
        )
        parser.add_argument(
            "--ttl", type=int, default=None, help="context lifetime in seconds (with --context)"
        )
        parser.add_argument(
            "--audit", action="store_true", help="record a policy_resolved audit event"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_id: str = options["user_id"]
        tenant: str = options["tenant"]
        source: str = options["source"]
        store = DjangoPolicyStore(audit_to_db=options["audit"])
        try:
            if options["context"]:
                ttl = timedelta(seconds=options["ttl"]) if options["ttl"] is not None else None
                context = issue_context(user_id, tenant, source, store=store, ttl=ttl)
                self.stdout.write(serialize_context(context))
                return
            policy = json.loads(serialize(store.resolve_policy(user_id, tenant, source)))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            raise CommandError(f"resolution failed: {exc!r}") from exc
        if options["assignments"]:
            assignments = [
                {
                    "policy": a.policy_name,
                    "assignee": f"{a.assignee.type.value}:{a.assignee.identifier}",
                    "tenant": a.scope.tenant_id,
                    "source": a.scope.source_connection_id,
                    "expiresAt": a.expires_at,
                }
                for a in store.get_assignments(user_id, tenant)
            ]
            self.stdout.write(json.dumps({"assignments": assignments, "policy": policy}, indent=2))
            return
        self.stdout.write(json.dumps(policy, indent=2))
