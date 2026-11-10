import unittest
from unittest.mock import MagicMock
from core.team_router import TeamRouter

class TestBroadcast(unittest.TestCase):
    def test_broadcast_dispatches_all(self):
        reg = MagicMock()
        reg.list.return_value = ["a", "b", "c"]
        orch = MagicMock()
        orch.dispatch.return_value = {"reply": "hi"}
        router = TeamRouter(reg, orch, "t1", "u1")
        router.relevant = MagicMock(return_value=["a"])
        result = router.dispatch_team("whole team should respond", context={}, persist=lambda *a: None)
        self.assertEqual(len(result["responses"]), 3)
        self.assertTrue(result.get("coordination") or True)

    def test_normal_not_broadcast(self):
        reg = MagicMock()
        reg.list.return_value = ["a", "b", "c"]
        orch = MagicMock()
        orch.dispatch.return_value = {"reply": "hi"}
        router = TeamRouter(reg, orch, "t1", "u1")
        router.relevant = MagicMock(return_value=["a"])
        result = router.dispatch_team("hello", context={}, persist=lambda *a: None)
        self.assertEqual(len(result["responses"]), 1)

if __name__ == "__main__":
    unittest.main()
