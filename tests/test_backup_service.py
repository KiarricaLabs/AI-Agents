"""M11 — managed backup & recovery (isolated DB, never production)."""
from __future__ import annotations

import os
import tempfile
import unittest

from cryptography.fernet import Fernet

from storage.database import Database
from core.backup_service import (
    backup_to_dir, restore_from, verify_backup, list_backups,
)


def _fresh_db() -> str:
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(p)
    return p


class TestBackupService(unittest.TestCase):
    def test_plain_backup_then_restore(self):
        src = _fresh_db()
        db = Database(path=src, tenant_id="t1")
        db.execute("INSERT INTO tenants (id,name,created_at) VALUES (?,?,?)",
                   ("marker", "x", "now"))
        db.commit() if hasattr(db, "commit") else None

        bdir = tempfile.mkdtemp(prefix="pat-backup-")
        dest = backup_to_dir(src, bdir, key=None)
        self.assertTrue(os.path.exists(dest))

        # mutate the source after backup
        db = Database(path=src, tenant_id="t1")
        db.execute("INSERT INTO tenants (id,name,created_at) VALUES (?,?,?)",
                   ("post", "x", "now"))

        # restore over the source
        restore_from(dest, src, key=None)
        db2 = Database(path=src, tenant_id="t1")
        self.assertTrue(db2.query("SELECT id FROM tenants WHERE id='marker'"))
        self.assertEqual(db2.query("SELECT id FROM tenants WHERE id='post'"), [])
        os.remove(src)
        os.remove(dest)

    def test_encrypted_backup_then_restore_and_corruption_of_source(self):
        src = _fresh_db()
        db = Database(path=src, tenant_id="t1")
        db.execute("INSERT INTO tenants (id,name,created_at) VALUES (?,?,?)",
                   ("enc_marker", "x", "now"))

        key = Fernet.generate_key()
        bdir = tempfile.mkdtemp(prefix="pat-backup-enc-")
        dest = backup_to_dir(src, bdir, key=key)
        # Encrypted file must not contain the plaintext marker string.
        with open(dest, "rb") as f:
            self.assertNotIn(b"enc_marker", f.read())

        # Destroy the source, then restore from encrypted backup.
        os.remove(src)
        restore_from(dest, src, key=key)
        db2 = Database(path=src, tenant_id="t1")
        self.assertTrue(db2.query("SELECT id FROM tenants WHERE id='enc_marker'"))

        # Wrong key must fail.
        wrong = Fernet.generate_key()
        with self.assertRaises(Exception):
            restore_from(dest, src + "2.db", key=wrong)
        os.remove(src)
        os.remove(dest)

    def test_verify_backup_integrity(self):
        src = _fresh_db()
        Database(path=src, tenant_id="t1")
        bdir = tempfile.mkdtemp(prefix="pat-backup-verify-")
        dest = backup_to_dir(src, bdir, key=None)
        res = verify_backup(dest, key=None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["integrity"], "ok")
        os.remove(src)
        os.remove(dest)

    def test_retention_prunes_old_backups(self):
        src = _fresh_db()
        Database(path=src, tenant_id="t1")
        bdir = tempfile.mkdtemp(prefix="pat-backup-ret-")
        dests = []
        for _ in range(5):
            dests.append(backup_to_dir(src, bdir, key=None, keep=3))
        remaining = list_backups(bdir)
        self.assertLessEqual(len(remaining), 3)
        os.remove(src)
        for d in dests:
            if os.path.exists(d):
                os.remove(d)


if __name__ == "__main__":
    unittest.main()
