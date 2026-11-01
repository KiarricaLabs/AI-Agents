import os, tempfile, unittest
from storage.database import Database
from core.workspace import WorkspaceService, ProjectService, GoalService, AssignmentService, DeliverableService


class TestM5(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(self.path)
        self.db = Database(path=self.path, tenant_id="t1")
        self.ws = WorkspaceService(self.db, "t1", "u1")
        self.ps = ProjectService(self.db, "t1", "u1")
        self.gs = GoalService(self.db, "t1", "u1")
        self.ass = AssignmentService(self.db, "t1", "u1")
        self.ds = DeliverableService(self.db, "t1", "u1")

    def tearDown(self):
        try: os.remove(self.path)
        except OSError: pass

    def test_workspace_project_goal(self):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        gid = self.gs.create(pid, "g1", priority=5)
        self.assertTrue(wid and pid and gid)

    def test_assignment_duplicate_blocked(self):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        gid = self.gs.create(pid, "g1")
        self.ass.assign(gid, "tutor")
        with self.assertRaises(ValueError):
            self.ass.assign(gid, "tutor")

    def test_deliverable_versioning_approval(self):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        did = self.ds.create(pid, "d1")
        v1, _ = self.ds.add_version(did, "content1")
        self.ds.approve(v1, "u1")
        v2, _ = self.ds.add_version(did, "content2")
        # approved v1 immutable status stays approved
        vs = self.ds.list_versions(did)
        self.assertEqual(vs[0]["status"], "approved")
        # reject v2
        self.ds.reject(v2, "u1")
        vs2 = self.ds.list_versions(did)
        self.assertEqual(vs2[1]["status"], "rejected")

    def test_tenant_isolation(self):
        wid = self.ws.create("w1")
        ws2 = WorkspaceService(Database(path=self.path, tenant_id="t2"), "t2", "u1")
        self.assertEqual(ws2.list(), [])

    def test_priority_ordering(self):
        wid = self.ws.create("w1")
        pid = self.ps.create(wid, "p1")
        self.gs.create(pid, "low", priority=1)
        self.gs.create(pid, "high", priority=10)
        goals = self.gs.list(pid)
        self.assertEqual(goals[0]["title"], "high")


if __name__ == "__main__":
    unittest.main()