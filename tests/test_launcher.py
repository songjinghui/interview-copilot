"""Windows loopback launcher primitives, only temporary paths and port probes."""

import os
from pathlib import Path
import tempfile
import unittest
from tests.test_storage import feature


@unittest.skipUnless(os.name == "nt", "Windows launcher")
class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.module = feature(self, "interview_copilot.launcher")

    def test_directory_instance_lock_rejects_second_holder_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.module.InstanceLock(Path(directory)):
                with self.assertRaises(OSError):
                    with self.module.InstanceLock(Path(directory)):
                        self.fail("second service acquired the same directory")
            with self.module.InstanceLock(Path(directory)):
                pass

    def test_authenticated_ipc_returns_nonce_for_exact_directory(self):
        from interview_copilot.session import Sessions

        with tempfile.TemporaryDirectory() as directory:
            sessions = Sessions(b"test-only-secret" * 3)
            with self.module.BootstrapPipe(Path(directory), sessions, 17863):
                url = self.module.request_open(Path(directory), sessions.key)
                self.assertTrue(url.startswith("http://127.0.0.1:17863/#bootstrap="))
                token = sessions.exchange(url.split("=", 1)[1])
                self.assertTrue(sessions.verify(token))

    def test_port_collision_is_rejected_without_connecting_to_listener(self):
        with self.module.reserve_port(0) as listener:
            port = listener.getsockname()[1]
            with self.assertRaises(OSError):
                with self.module.reserve_port(port):
                    self.fail("reused an occupied local port")

    def test_rejected_ipc_auth_does_not_stop_accepting_authorized_clients(self):
        from multiprocessing import AuthenticationError
        from unittest.mock import patch, Mock
        from interview_copilot.session import Sessions

        with tempfile.TemporaryDirectory() as directory:
            server = self.module.BootstrapPipe(
                Path(directory), Sessions(b"test-only-secret" * 3), 17863
            )
            connection = Mock()
            connection.__enter__ = Mock(return_value=connection)
            connection.__exit__ = Mock(return_value=False)
            server.listener = Mock()
            server.listener.accept.side_effect = [connection, OSError("test end")]
            with patch.object(
                self.module,
                "deliver_challenge",
                side_effect=AuthenticationError("wrong key"),
            ):
                server._serve()
            self.assertEqual(server.listener.accept.call_count, 2)
