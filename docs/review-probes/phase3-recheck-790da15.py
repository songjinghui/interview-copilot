"""Independent delta probes, isolated data only; explicit checkout required."""
import importlib.util
from pathlib import Path
import sys
import unittest
from datetime import timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfoNotFoundError

checkout = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(checkout))
spec = importlib.util.spec_from_file_location(
    "original_phase3_review",
    Path(__file__).with_name("phase3-service-2026-11-06.py"),
)
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)  # consumes the checkout argument; imports src
from interview_copilot.application import ApplicationError
from tests.test_audio_import import AudioImportTest


def zone(name):
    if name == "Asia/Shanghai":
        return timezone(timedelta(hours=8))
    if name == "UTC":
        return timezone.utc
    raise ZoneInfoNotFoundError(name)


class AudioIdentityReview(unittest.TestCase):
    def setUp(self):
        self.fixture = AudioImportTest()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.asset_id, self.path, self.payload = self.fixture.add_asset()
        self.request = str(uuid4())

    def attach(self):
        return self.fixture.command(
            "AttachAudioImport", request_id=self.request,
            interview_id=self.fixture.interview_id, asset_id=self.asset_id,
        )

    def test_replacement_after_decode_before_identity_capture_is_rejected(self):
        service = self.fixture.service
        original_audio = service._audio_file

        def replace_after_validation(asset):
            result = original_audio(asset)
            # Different bytes, same length, ordinary write (no forged timestamps).
            self.path.write_bytes(b"x" * len(self.payload))
            return result

        with patch.object(service, "_audio_file", side_effect=replace_after_validation):
            with self.assertRaises(ApplicationError):
                self.attach()
        for table in ("audio_assets", "audio_parts", "background_tasks", "transcription_jobs"):
            self.assertEqual(
                self.fixture.db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0
            )

    def test_replacement_after_preflight_is_rejected(self):
        service = self.fixture.service
        original_prepare = service.prepare_command

        def replace_after_preflight(command, payload):
            result = original_prepare(command, payload)
            self.path.write_bytes(b"x" * (len(self.payload) + 1))
            return result

        with patch.object(service, "prepare_command", side_effect=replace_after_preflight):
            with self.assertRaises(ApplicationError):
                self.attach()
        self.assertEqual(
            self.fixture.db.connection.execute("SELECT count(*) FROM audio_assets").fetchone()[0], 0
        )

    def test_committed_receipt_replay_does_not_reread_missing_file(self):
        saved = self.attach()
        self.path.unlink()  # exact synthetic test file, never user data
        self.assertEqual(self.attach(), saved)


if __name__ == "__main__":
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(original.ReviewTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(AudioIdentityReview),
    ])
    # Existing A1-A4 assertions remain unchanged. Give their fixture a valid
    # resolver now that missing tzdb is deliberately rejected. No tzdb installed.
    with patch("interview_copilot.workbench.ZoneInfo", side_effect=zone), patch(
        "interview_copilot.workbench.available_timezones",
        return_value={"UTC", "Asia/Shanghai"},
    ):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

