"""Simple polling scheduler (Phase B2) — enqueues runs on an interval."""
from __future__ import annotations
import threading
import time
from datetime import datetime, timezone


class Scheduler:
    def __init__(self, enqueue_fn, interval_seconds=300):
        self.enqueue_fn = enqueue_fn
        self.interval = interval_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _loop(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.enqueue_fn()
            except Exception:
                pass
"""