import os, tempfile, unittest
from storage.database import Database
from core.delegation import DelegationService
from core.messagebus import MessageBus
from core.episodes import EpisodeService


class TestM4(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.manifests = {
            "workspace_architect": {"permissions": ["memory:read"], "delegates_to": ["strategist"], "delegated_from": []},
            "strategist": {"permissions": ["memory:read"], "delegates_to": [], "delegated_from": ["workspace_architect"]},
        }
        self.ds = DelegationService(db=self.db, tenant_id="t1", manifests=self.manifests)

    def tearDown(self):
        try: os.remove(self.path)
        except OSError: pass

    def test_delegation_allowed(self):
        res = self.ds.delegate("workspace_architect", "strategist", "task")
        self.assertEqual(res["to"], "strategist")

    def test_delegation_denied(self):
        with self.assertRaises(PermissionError):
            self.ds.delegate("strategist", "workspace_architect", "task")

    def test_depth_limit(self):
        ok, info = self.ds.can_delegate("workspace_architect", "strategist", depth=3)
        self.assertFalse(ok)

    def test_messagebus_auth(self):
        bus = MessageBus("t1")
        bus.authorize_topic("updates", ["agent1"])
        with self.assertRaises(PermissionError):
            bus.subscribe("updates", "agent2", lambda m: None)

    def test_episode_checkpoint_recovery(self):
        es = EpisodeService(db=self.db, tenant_id="t1", user_id="u1")
        eid = es.start("workspace_architect")
        es.checkpoint(eid, 50, {"step": 1})
        t = es.get(eid)
        self.assertEqual(t["progress"], 50)
        # cancel terminal
        es.cancel(eid)
        self.assertFalse(es.complete(eid))

    def test_checkpoint_secrets_rejected(self):
        es = EpisodeService(db=self.db, tenant_id="t1", user_id="u1")
        eid = es.start("workspace_architect")
        with self.assertRaises(ValueError):
            es.checkpoint(eid, 10, {"password": "x"})

    def test_episode_tenant_isolation(self):
        es = EpisodeService(db=self.db, tenant_id="t1", user_id="u1")
        eid = es.start("workspace_architect")
        es2 = EpisodeService(db=Database(path=self.path, tenant_id="t2"), tenant_id="t2", user_id="u1")
        self.assertIsNone(es2.get(eid))


if __name__ == "__main__":
    unittest.main()