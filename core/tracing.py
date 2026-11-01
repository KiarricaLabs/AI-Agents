"""Lightweight tracing hooks (no external deps)."""
from __future__ import annotations
import time

_spans = []


def start_span(name, attrs=None):
    span = {"name": name, "attrs": attrs or {}, "start": time.time()}
    _spans.append(span)
    return span


def end_span(span):
    span["end"] = time.time()
    span["duration"] = span["end"] - span["start"]


def get_spans():
    return list(_spans)