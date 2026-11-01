import os, tempfile, unittest
from storage.database import Database
from core.episodes import EpisodeService
from core.workspace import DeliverableService


class TestM6Backend(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")

    def tearDown(self):
        try: os.remove(self.path)
        except OSError: pass

    def test_episode_list_tenant_isolation(self):
        es1 = EpisodeService(self.db, "t1", "u1")
        eid = es1.start("tutor")
        es2 = EpisodeService(Database(path=self.path, tenant_id="t2"), "t2", "u1")
        self.assertIsNone(es2.get(eid))

    def test_episode_cancel_and_resume(self):
        es = EpisodeService(self.db, "t1", "u1")
        eid = es.start("tutor")
        self.assertTrue(es.cancel(eid))
        self.assertFalse(es.cancel(eid))  # already cancelled
        self.assertFalse(es.recover(eid, lambda *a: None))  # cancelled terminal

    def test_deliverable_listing_ownership(self):
        ds = DeliverableService(self.db, "t1", "u1")
        did = ds.create("p1", "d1")
        # other tenant shouldn't see
        rows = self.db.query("SELECT * FROM deliverables WHERE tenant_id=? AND project_id=?", ("t2", "p1"))
        self.assertEqual(rows, [])

    def test_rejection_reason_persisted(self):
        ds = DeliverableService(self.db, "t1", "u1")
        did = ds.create("p1", "d1")
        vid, _ = ds.add_version(did, "content")
        ds.reject(vid, "u1", reason="needs work")
        approvals = self.db.query("SELECT * FROM deliverable_approvals WHERE tenant_id=? AND version_id=?", ("t1", vid))
        self.assertTrue(any("needs work" in a["decision"] for a in approvals))

    def test_revision_creates_new_version(self):
        ds = DeliverableService(self.db, "t1", "u1")
        did = ds.create("p1", "d1")
        v1, ver1 = ds.add_version(did, "v1")
        ds.approve(v1, "u1")
        v2, ver2 = ds.add_version(did, "v2")
        self.assertEqual(ver2, ver1 + 1)
        versions = ds.list_versions(did)
        self.assertEqual(versions[0]["status"], "approved")
        self.assertEqual(versions[1]["status"], "draft")

    def test_approved_version_immutable(self):
        ds = DeliverableService(self.db, "t1", "u1")
        did = ds.create("p1", "d1")
        v1, _ = ds.add_version(did, "v1")
        ds.approve(v1, "u1")
        # approve again should raise
        with self.assertRaises(ValueError):
            ds.approve(v1, "u1")


if __name__ == "__main__":
    unittest.main()