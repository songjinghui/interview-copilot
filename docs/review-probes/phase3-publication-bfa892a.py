"""Check publication after real SQLite lock contention; temporary data only."""
import hashlib
from pathlib import Path
import sys
import threading
import unittest
from uuid import uuid4

checkout = Path(sys.argv.pop(1)).resolve()
sys.path[:0] = [str(checkout / "src"), str(checkout)]

from interview_copilot.application import ApplicationError
from interview_copilot.storage import Database
from interview_copilot.workbench import WorkbenchService
from tests.test_audio_import import AudioImportTest


class PublicationReview(unittest.TestCase):
    def setUp(self):
        self.fixture = AudioImportTest()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def attach_while_other_writer_holds_lock(self, asset_id, mutate):
        request = str(uuid4())
        begin_attempted, done = threading.Event(), threading.Event()
        outcome = {}

        def import_audio():
            try:
                with Database(self.fixture.database_path) as database:
                    def trace(statement):
                        if statement.strip().upper() == "BEGIN IMMEDIATE":
                            begin_attempted.set()

                    database.connection.set_trace_callback(trace)
                    outcome["result"] = WorkbenchService(database).execute(
                        request,
                        "AttachAudioImport",
                        {"interview_id": self.fixture.interview_id, "asset_id": asset_id},
                    )
            except Exception as error:
                outcome["error"] = error
            finally:
                done.set()

        blocker = self.fixture.db.connection
        blocker.execute("BEGIN IMMEDIATE")
        worker = threading.Thread(target=import_audio)
        worker.start()
        try:
            self.assertTrue(begin_attempted.wait(3), f"No BEGIN attempt: {outcome}")
            self.assertFalse(done.wait(0.05), "Expected a real blocked writer")
            # No mock of the importer: change only the isolated fixture while
            # its real BEGIN IMMEDIATE is waiting for the other connection.
            mutate()
            blocker.commit()
        finally:
            if blocker.in_transaction:
                blocker.rollback()
            worker.join(6)
        self.assertFalse(worker.is_alive(), "Import worker did not finish")
        return request, outcome

    def assert_no_import(self, request):
        for table in ("audio_assets", "audio_parts", "background_tasks", "transcription_jobs"):
            self.assertEqual(
                self.fixture.db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
                0,
                table,
            )
        self.assertIsNone(self.fixture.db.connection.execute(
            "SELECT 1 FROM command_receipts WHERE request_id=?", (request,)
        ).fetchone())

    def test_file_change_while_waiting_for_write_lock_cannot_be_published(self):
        asset_id, path, payload = self.fixture.add_asset()
        mutation = {"denied": False}

        def overwrite():
            try:
                path.write_bytes(b"x" * len(payload))
            except PermissionError:
                # A file-sharing guard that prevents the change is also valid.
                mutation["denied"] = True

        request, outcome = self.attach_while_other_writer_holds_lock(asset_id, overwrite)
        if mutation["denied"]:
            self.assertEqual(path.read_bytes(), payload)
            self.assertIn("result", outcome)
        else:
            self.assertNotEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(payload).digest())
            self.assertIsInstance(
                outcome.get("error"), ApplicationError,
                f"Changed audio was accepted after the lock wait: {outcome}",
            )
            self.assert_no_import(request)

    def test_asset_metadata_change_while_waiting_for_write_lock_is_rejected(self):
        for field, value in (
            ("status", "missing"), ("relative_path", "audio/changed.wav"),
            ("byte_size", 1), ("sha256", "0" * 64), ("media_type", "audio/mpeg"),
        ):
            with self.subTest(field=field):
                asset_id, _path, _payload = self.fixture.add_asset()

                def mutate():
                    self.fixture.db.connection.execute(
                        f"UPDATE file_assets SET {field}=? WHERE id=?", (value, asset_id)
                    )

                request, outcome = self.attach_while_other_writer_holds_lock(asset_id, mutate)
                self.assertIsInstance(outcome.get("error"), ApplicationError, outcome)
                self.assertEqual(outcome["error"].code, "INVALID_STATE")
                self.assert_no_import(request)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicationReview)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
