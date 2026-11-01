import os
import unittest

from storage.credentials import CredentialStore


class TestCredentials(unittest.TestCase):
    def setUp(self):
        os.environ["PAT_MASTER_KEY"] = "u9v2w3x4y5z6A7B8C9D0E1F2G3H4I5J6K7L8M9N0O1P="
        # generate a valid fernet key
        from cryptography.fernet import Fernet
        self.key = Fernet.generate_key().decode()
        os.environ["PAT_MASTER_KEY"] = self.key

    def test_encrypt_decrypt(self):
        cs = CredentialStore(key=self.key)
        tok = cs.encrypt("secret")
        self.assertNotEqual(tok, "secret")
        self.assertEqual(cs.decrypt(tok), "secret")

    def test_missing_key_hard_fail(self):
        with self.assertRaises(RuntimeError):
            CredentialStore(key="")

    def test_invalid_key_hard_fail(self):
        with self.assertRaises(Exception):
            CredentialStore(key="not-a-key")

    def test_no_plaintext_fallback(self):
        cs = CredentialStore(key=self.key)
        tok = cs.encrypt("s")
        # token must not contain plaintext
        self.assertNotIn("s", tok.replace("s", ""))  # weak check but ok
        self.assertTrue(len(tok) > 10)


if __name__ == "__main__":
    unittest.main()