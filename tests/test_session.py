"""Local bootstrap and session expiry, no actual user credentials."""

import tempfile
import unittest
from pathlib import Path
from tests.test_storage import feature


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, "interview_copilot.session")
        self.now = 1000
        self.manager = self.module.Sessions(
            b"test-only-key" * 4, clock=lambda: self.now
        )

    def test_nonce_is_single_use_and_expires(self):
        nonce = self.manager.bootstrap()
        self.assertTrue(self.manager.verify(self.manager.exchange(nonce)))
        with self.assertRaises(ValueError):
            self.manager.exchange(nonce)
        expired = self.manager.bootstrap()
        self.now += 61
        with self.assertRaises(ValueError):
            self.manager.exchange(expired)

    def test_token_survives_restart_renews_only_when_valid_and_rejects_tampering(self):
        token = self.manager.exchange(self.manager.bootstrap())
        restarted = self.module.Sessions(b"test-only-key" * 4, clock=lambda: self.now)
        self.now += 28000
        renewed = restarted.renew(token)
        self.now += 1000
        self.assertTrue(restarted.verify(renewed))
        for bad in (token, renewed + "tamper", "invalid", "", None):
            with self.assertRaises(ValueError):
                restarted.renew(bad)

    def test_windows_key_is_persisted_encrypted_and_corruption_fails_closed(self):
        import os

        if os.name != "nt":
            self.skipTest("DPAPI requires Windows")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.key"
            first = self.module.load_key(path)
            self.assertEqual(first, self.module.load_key(path))
            self.assertNotIn(first, path.read_bytes())
            path.write_bytes(b"damaged")
            with self.assertRaises(OSError):
                self.module.load_key(path)
