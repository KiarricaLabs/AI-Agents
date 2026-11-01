import os, tempfile, unittest
from cryptography.fernet import Fernet
from core.backup import encrypted_backup, encrypted_restore
from core.metrics import inc, render
from core.tracing import start_span, end_span, get_spans


class TestPhase2(unittest.TestCase):
    def test_encrypted_backup_restore(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(path)
        from storage.database import Database
        Database(path=path, tenant_id="t1")
        key = Fernet.generate_key()
        bpath = path + ".enc"
        encrypted_backup(path, bpath, key)
        # ensure key not stored alongside
        self.assertFalse(os.path.exists(bpath + ".key"))
        os.remove(path)
        encrypted_restore(bpath, path, key)
        db2 = Database(path=path, tenant_id="t1")
        self.assertIsNotNone(db2)
        os.remove(path); os.remove(bpath)

    def test_wrong_key_fails(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(path)
        from storage.database import Database
        Database(path=path, tenant_id="t1")
        key = Fernet.generate_key()
        bpath = path + ".enc"
        encrypted_backup(path, bpath, key)
        wrong = Fernet.generate_key()
        with self.assertRaises(Exception):
            encrypted_restore(bpath, path, wrong)
        os.remove(path); os.remove(bpath)

    def test_metrics(self):
        inc("requests_total", {"method": "GET"}, 1)
        out = render()
        self.assertIn("requests_total", out)

    def test_tracing(self):
        s = start_span("op", {"x": 1})
        end_span(s)
        spans = get_spans()
        self.assertTrue(any(sp["name"] == "op" for sp in spans))


if __name__ == "__main__":
    unittest.main()