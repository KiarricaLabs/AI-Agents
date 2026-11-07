import os
import tempfile
import unittest
from storage.database import Database
from storage.credentials import CredentialStore


class PersistentCredentialTests(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.gettempdir(), "cred_test.db")
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass
        self.db = Database(path=self.db_path, tenant_id="t1")
        import os as _os
        self.key = _os.urandom(32)
        import base64
        self.fernet_key = base64.urlsafe_b64encode(self.key).decode()
        self.cs = CredentialStore(db=self.db, tenant_id="t1", user_id="u1", key=self.fernet_key)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except FileNotFoundError:
            pass

    def test_save_and_retrieve(self):
        self.cs.save("email", "secret123")
        self.assertEqual(self.cs.retrieve("email"), "secret123")

    def test_plaintext_not_in_db(self):
        self.cs.save("email", "secret123")
        rows = self.db.query("SELECT encrypted_payload FROM credentials WHERE provider='email'")
        self.assertNotIn("secret123", rows[0]["encrypted_payload"])

    def test_update_replaces(self):
        self.cs.save("email", "old")
        self.cs.save("email", "new")
        self.assertEqual(self.cs.retrieve("email"), "new")

    def test_delete(self):
        self.cs.save("email", "secret")
        self.cs.delete("email")
        self.assertFalse(self.cs.exists("email"))

    def test_wrong_key_fails(self):
        self.cs.save("email", "secret")
        import base64, os as _os
        other_key = base64.urlsafe_b64encode(_os.urandom(32)).decode()
        cs2 = CredentialStore(db=self.db, tenant_id="t1", user_id="u1", key=other_key)
        with self.assertRaises(Exception):
            cs2.retrieve("email")

    def test_missing_key_fails(self):
        import os as _os
        old = _os.environ.pop("PAT_MASTER_KEY", None)
        try:
            with self.assertRaises(Exception):
                CredentialStore(key="")
        finally:
            if old is not None:
                _os.environ["PAT_MASTER_KEY"] = old

    def test_provider_isolation(self):
        self.cs.save("email", "emailsec")
        self.cs.save("calendar", "calsec")
        self.assertEqual(self.cs.retrieve("email"), "emailsec")
        self.assertEqual(self.cs.retrieve("calendar"), "calsec")

    def test_owner_isolation(self):
        cs2 = CredentialStore(db=self.db, tenant_id="t2", user_id="u2", key=self.fernet_key)
        self.cs.save("email", "u1secret")
        with self.assertRaises(KeyError):
            cs2.retrieve("email")


if __name__ == "__main__":
    unittest.main()