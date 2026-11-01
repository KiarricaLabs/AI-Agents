"""Simple in-memory metrics (Prometheus-like text)."""
from __future__ import annotations

_counters = {}


def inc(name, labels=None, value=1):
    key = name + str(sorted((labels or {}).items()))
    _counters[key] = _counters.get(key, 0) + value


def render():
    lines = []
    for k, v in _counters.items():
        lines.append(f"{k} {v}")
    return "\n".join(lines)