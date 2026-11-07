import threading
import time
import unittest
from core.scheduler import Scheduler


class SchedulerTests(unittest.TestCase):
    def test_fires_enqueue_after_interval(self):
        calls = []
        s = Scheduler(lambda: calls.append(1), interval_seconds=0.05)
        s.start()
        time.sleep(0.2)
        s.stop()
        self.assertGreaterEqual(len(calls), 1)

    def test_stop_prevents_further_calls(self):
        calls = []
        s = Scheduler(lambda: calls.append(1), interval_seconds=0.05)
        s.start()
        time.sleep(0.12)
        s.stop()
        n = len(calls)
        time.sleep(0.15)
        self.assertEqual(len(calls), n)

    def test_enqueue_exception_does_not_kill_scheduler(self):
        calls = {"n": 0}
        def boom():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
        s = Scheduler(boom, interval_seconds=0.05)
        s.start()
        time.sleep(0.2)
        s.stop()
        self.assertGreaterEqual(calls["n"], 2)

    def test_multiple_schedulers_independent(self):
        a, b = [], []
        sa = Scheduler(lambda: a.append(1), interval_seconds=0.05)
        sb = Scheduler(lambda: b.append(1), interval_seconds=0.05)
        sa.start(); sb.start()
        time.sleep(0.15)
        sa.stop(); sb.stop()
        self.assertGreaterEqual(len(a), 1)
        self.assertGreaterEqual(len(b), 1)


if __name__ == "__main__":
    unittest.main()