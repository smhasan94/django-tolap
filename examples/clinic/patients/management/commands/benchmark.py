"""Pushdown vs post-only on the same tool, same policy, same rows.

Reports the SQL each mode sent, rows the database returned, peak resident memory delta,
and median wall time. Both modes return identical rows (checked; a mismatch is an error).

Memory is ``ru_maxrss``, a process-lifetime high-water mark. The modes therefore run from
lightest to heaviest (pushdown first), so each delta is the growth that mode itself caused.
"""

from __future__ import annotations

import gc
import resource
import statistics
import sys
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext

from django_tolap import EnforcementMode, enforce, issue_context
from patients.models import Patient
from patients.tools import SOURCE

MODES = [EnforcementMode.rewrite_and_post, EnforcementMode.post_only]


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


class Command(BaseCommand):
    help = "Compare rewrite_and_post with post_only for one user and one query."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--user", default="alice")
        parser.add_argument("--q", default="")
        parser.add_argument("--runs", type=int, default=5)
        parser.add_argument("--markdown", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        context = issue_context(options["user"], "clinic", SOURCE)
        total = Patient.objects.count()
        results: dict[str, dict[str, Any]] = {}
        outputs: dict[str, list[dict[str, Any]]] = {}
        for mode in MODES:
            timings = []
            fetched = 0
            sql = ""
            outputs[mode.value] = []
            gc.collect()
            rss_before = _peak_rss_mb()
            for _ in range(options["runs"]):
                qs = Patient.objects.order_by("id")
                if options["q"]:
                    qs = qs.filter(full_name__icontains=options["q"])
                reset_queries()
                with CaptureQueriesContext(connection) as captured:
                    start = time.perf_counter()
                    rows = enforce(qs, context, mode=mode)
                    timings.append(time.perf_counter() - start)
                sql = captured.captured_queries[-1]["sql"] if captured.captured_queries else ""
                fetched = _rows_fetched(qs, mode, context)
                outputs[mode.value] = rows
            results[mode.value] = {
                "sql": sql,
                "fetched": fetched,
                "returned": len(outputs[mode.value]),
                "median_s": statistics.median(timings),
                "peak_rss_delta_mb": max(0.0, _peak_rss_mb() - rss_before),
            }
        if outputs[MODES[0].value] != outputs[MODES[1].value]:
            raise CommandError(
                "modes disagree: rewriteAndPost and postOnly returned different rows"
            )
        self._report(total, results, options["markdown"])

    def _report(self, total: int, results: dict[str, dict[str, Any]], markdown: bool) -> None:
        vendor = connection.vendor
        if markdown:
            self.stdout.write(
                f"| Mode ({vendor}, {total:,} rows) | Rows fetched | Rows returned | Median wall time | Peak RSS delta |"
            )
            self.stdout.write("| --- | ---: | ---: | ---: | ---: |")
            for mode, r in results.items():
                self.stdout.write(
                    f"| `{mode}` | {r['fetched']:,} | {r['returned']:,} | {r['median_s'] * 1000:,.0f} ms | {r['peak_rss_delta_mb']:,.0f} MB |"
                )
            self.stdout.write("")
            for mode, r in results.items():
                self.stdout.write(f"`{mode}` SQL:\n\n```sql\n{r['sql']}\n```\n")
        else:
            for mode, r in results.items():
                self.stdout.write(
                    f"== {mode} ==\n  sql: {r['sql'][:300]}\n  fetched={r['fetched']:,} returned={r['returned']:,} median={r['median_s'] * 1000:.0f}ms peak_rss_delta={r['peak_rss_delta_mb']:.0f}MB"
                )


def _rows_fetched(qs: Any, mode: EnforcementMode, context: Any) -> int:
    """How many rows the database handed back before the post pass, for this mode."""
    from django_tolap.pushdown import prepare_queryset

    prep = prepare_queryset(qs, context.effective_policy, mode=mode)
    return prep.queryset.count() if prep.allowed and prep.queryset is not None else 0
