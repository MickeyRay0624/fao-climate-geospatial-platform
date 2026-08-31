from __future__ import annotations

from collections import Counter
from threading import Lock


_COUNTERS: Counter[str] = Counter()
_LOCK = Lock()


def increment(name: str, amount: float = 1) -> None:
    with _LOCK:
        _COUNTERS[name] += amount


def snapshot() -> dict[str, float]:
    with _LOCK:
        return dict(_COUNTERS)


def prometheus_text() -> str:
    values = snapshot()
    names = [
        "investment_runs_total",
        "investment_run_duration_seconds",
        "investment_run_failures_total",
        "investment_output_registration_failures_total",
        "investment_legacy_backfill_total",
    ]
    lines = ["# Phase 2A in-process development metrics; aggregate externally in production."]
    for name in names:
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {values.get(name, 0)}")
    return "\n".join(lines) + "\n"
