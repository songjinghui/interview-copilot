"""Regression probes for the phase-3 independent service review findings."""

import hashlib
import io
import tempfile
import threading
import unittest
import uuid
import wave
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from fastapi.testclient import TestClient

from interview_copilot.application import ApplicationError
from interview_copilot.http import create_app
from interview_copilot.session import Sessions
from interview_copilot.storage import Database
from interview_copilot.storage.database import utc_now
from interview_copilot.workbench import WorkbenchService


class Phase3ServiceReviewRegressionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase3-service-review-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database_path = self.root / "app.sqlite"
        self.db = Database(self.database_path)
        self.addCleanup(self.db.close)
        self.service = WorkbenchService(self.db)
        self.opportunity = self.command(
            "SaveOpportunity", title="Synthetic", company_name="Review"
        )
        self.timezones = patch(
            "interview_copilot.workbench.available_timezones",
            return_value={"Asia/Shanghai", "UTC"},
        )
        self.timezones.start()
        self.addCleanup(self.timezones.stop)
        self.zone_resolver = patch(
            "interview_copilot.workbench.ZoneInfo",
            side_effect=self.resolve_test_zone,
        )
        self.zone_resolver.start()
        self.addCleanup(self.zone_resolver.stop)

    @staticmethod
    def resolve_test_zone(name):
        zones = {
            "Asia/Shanghai": timezone(timedelta(hours=8)),
            "UTC": timezone.utc,
        }
        try:
            return zones[name]
        except KeyError:
            raise ZoneInfoNotFoundError(name) from None

    def command(self, name, expected=None, **payload):
        return self.service.execute(
            str(uuid.uuid4()), name, payload, expected_revision=expected
        )["data"]

    def interview(self, **changes):
        payload = {
            "opportunity_id": self.opportunity["id"],
            "label": "Synthetic interview",
            "starts_at": "2030-11-20T10:00:00+08:00",
            "ends_at": "2030-11-20T11:00:00+08:00",
            "time_zone": "Asia/Shanghai",
            "format": "online",
            "status": "planned",
            "reminder_offsets": [60],
        }
        payload.update(changes)
        return self.command("SaveInterview", **payload)

    def client(self):
        sessions = Sessions(b"isolated-review-key" * 3)
        origin = "http://127.0.0.1:17863"
        app = create_app(self.database_path, sessions)
        token = sessions.exchange(sessions.bootstrap())
        client = TestClient(app, base_url=origin)
        self.addCleanup(client.close)
        return client, {"Authorization": "Bearer " + token, "Origin": origin}

    def test_A1_opportunity_filter_accepts_the_domain_status_vocabulary(self):
        client, headers = self.client()
        results = {}
        for status in (
            "saved", "deferred", "applying", "applied", "interviewing",
            "offer", "rejected", "withdrawn", "archived",
        ):
            self.opportunity = self.command(
                "UpdateOpportunity",
                expected=self.opportunity["revision"],
                id=self.opportunity["id"],
                status=status,
            )
            response = client.get(
                "/api/v1/opportunities?status=" + status, headers=headers
            )
            results[status] = response.status_code
        self.assertEqual(results, dict.fromkeys(results, 200))

    def test_A2_unknown_zone_is_rejected_when_zone_database_is_available(self):
        def resolver(name):
            if name == "Asia/Shanghai":
                return timezone(timedelta(hours=8))
            raise ZoneInfoNotFoundError(name)

        with (
            patch("interview_copilot.workbench.ZoneInfo", side_effect=resolver),
            patch("interview_copilot.workbench.available_timezones", return_value={"Asia/Shanghai", "UTC"}),
        ):
            self.interview()
            with self.assertRaises(ApplicationError):
                self.interview(time_zone="Not/A_Real_Zone")

    def test_A3_utc_query_timestamps_roundtrip_with_display_zone(self):
        with patch(
            "interview_copilot.workbench.ZoneInfo",
            return_value=timezone(timedelta(hours=8)),
        ), patch("interview_copilot.workbench.available_timezones", return_value={"Asia/Shanghai", "UTC"}):
            created = self.interview()
            view = self.service.query("interviews/" + created["id"])["schedule"]
            self.assertEqual(view["starts_at"], "2030-11-20T02:00:00.000Z")
            updated = self.command(
                "SaveInterview",
                expected=view["revision"],
                id=view["id"],
                opportunity_id=view["opportunity_id"],
                label="Label correction",
                starts_at=view["starts_at"],
                ends_at=view["ends_at"],
                time_zone=view["time_zone"],
                format=view["format"],
                status=view["status"],
                reminder_offsets=[60],
            )
            self.assertEqual(updated["starts_at"], view["starts_at"])

    def test_A4_slow_audio_validation_does_not_block_authenticated_profile(self):
        interview = self.interview()
        asset_id = str(uuid.uuid4())
        relative = f"audio/{asset_id}.wav"
        file_path = self.root / "assets" / relative
        file_path.parent.mkdir(parents=True)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\0\0" * 1600)
        payload = buffer.getvalue()
        file_path.write_bytes(payload)
        self.service._insert(
            "file_assets",
            id=asset_id,
            kind="audio",
            status="ready",
            relative_path=relative,
            original_name="synthetic.wav",
            media_type="audio/wav",
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            intent_json="{}",
            created_at=utc_now(),
            finalized_at=utc_now(),
        )
        client, headers = self.client()
        entered, release = threading.Event(), threading.Event()
        errors = []
        original_audio_file = WorkbenchService._audio_file

        original_audio_file = WorkbenchService._audio_file

        def delayed(_service, asset):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test gate timed out")
            return original_audio_file(_service, asset)

        def attach():
            try:
                with Database(self.database_path) as database:
                    WorkbenchService(database).execute(
                        str(uuid.uuid4()),
                        "AttachAudioImport",
                        {"interview_id": interview["id"], "asset_id": asset_id},
                    )
            except BaseException as error:  # surfaced in the assertion below
                errors.append(error)

        with patch.object(WorkbenchService, "_audio_file", delayed):
            worker = threading.Thread(target=attach)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                with Database(self.database_path) as concurrent_database:
                    concurrent_service = WorkbenchService(concurrent_database)
                    changed_opportunity = concurrent_service.execute(
                        str(uuid.uuid4()),
                        "UpdateOpportunity",
                        {"id": self.opportunity["id"], "note": "写锁未被音频 I/O 占用"},
                        expected_revision=self.opportunity["revision"],
                    )["data"]
                    self.assertEqual(changed_opportunity["note"], "写锁未被音频 I/O 占用")
                # Keep lock waits short while preserving the real HTTP/database path.
                from interview_copilot import http as http_module

                real_database = http_module.Database

                def short_wait_database(path):
                    database = real_database(path)
                    database.connection.execute("PRAGMA busy_timeout=100")
                    return database

                with patch.object(http_module, "Database", side_effect=short_wait_database):
                    response = client.get("/api/v1/profile", headers=headers)
            finally:
                release.set()
                worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(response.status_code, 200, response.text)

    def test_no_tzdb_is_an_explicit_capability_failure_not_silent_acceptance(self):
        with patch("interview_copilot.workbench.available_timezones", return_value=set()), patch(
            "interview_copilot.workbench.ZoneInfo", side_effect=ZoneInfoNotFoundError
        ):
            with self.assertRaises(ApplicationError) as caught:
                self.interview()
        self.assertEqual(caught.exception.code, "TIMEZONE_DATA_UNAVAILABLE")

    def test_audio_replacement_during_validation_is_detected_from_open_handle(self):
        interview = self.interview()
        asset_id, path, payload = self._registered_audio_asset()
        import interview_copilot.workbench as workbench

        real_wave_open = workbench.wave.open

        def mutate_after_wav_header(stream, *args, **kwargs):
            opened = real_wave_open(stream, *args, **kwargs)
            # Mutate after the importer has parsed the header, but before it
            # finishes reading/decoding the actual PCM frames.
            original_readframes = opened.readframes

            def mutate_then_read(frames):
                path.write_bytes(b"x" * len(payload))
                opened.readframes = original_readframes
                return original_readframes(frames)

            opened.readframes = mutate_then_read
            return opened

        with patch.object(workbench.wave, "open", side_effect=mutate_after_wav_header):
            with self.assertRaises(ApplicationError):
                self.service.execute(
                    str(uuid.uuid4()),
                    "AttachAudioImport",
                    {"interview_id": interview["id"], "asset_id": asset_id},
                )
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM audio_assets").fetchone()[0], 0
        )

    def _attach_while_write_lock_is_held(self, interview_id, asset_id, mutate):
        request_id = str(uuid.uuid4())
        begin_attempted, done = threading.Event(), threading.Event()
        outcome = {}

        def attach():
            try:
                with Database(self.database_path) as database:
                    database.connection.set_trace_callback(
                        lambda statement: begin_attempted.set()
                        if statement.strip().upper() == "BEGIN IMMEDIATE"
                        else None
                    )
                    outcome["result"] = WorkbenchService(database).execute(
                        request_id,
                        "AttachAudioImport",
                        {"interview_id": interview_id, "asset_id": asset_id},
                    )
            except BaseException as error:
                outcome["error"] = error
            finally:
                done.set()

        blocker = self.db.connection
        blocker.execute("BEGIN IMMEDIATE")
        worker = threading.Thread(target=attach)
        worker.start()
        try:
            self.assertTrue(begin_attempted.wait(3), f"No BEGIN attempt: {outcome}")
            self.assertFalse(done.wait(0.05), "Expected writer to wait for the lock")
            mutate()
            blocker.commit()
        finally:
            if blocker.in_transaction:
                blocker.rollback()
            worker.join(6)
        self.assertFalse(worker.is_alive(), "Import worker did not finish")
        return request_id, outcome

    def assert_no_published_audio(self, request_id):
        for table in ("audio_assets", "audio_parts", "background_tasks", "transcription_jobs"):
            self.assertEqual(
                self.db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
                0,
                table,
            )
        self.assertIsNone(
            self.db.connection.execute(
                "SELECT 1 FROM command_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
        )

    def test_file_changed_while_waiting_for_write_lock_is_not_published(self):
        interview = self.interview()
        asset_id, path, payload = self._registered_audio_asset()
        request_id, outcome = self._attach_while_write_lock_is_held(
            interview["id"], asset_id, lambda: path.write_bytes(b"x" * len(payload))
        )
        self.assertIsInstance(outcome.get("error"), ApplicationError, outcome)
        self.assertEqual(outcome["error"].code, "INVALID_STATE")
        self.assert_no_published_audio(request_id)

    def test_asset_metadata_changed_while_waiting_for_write_lock_is_not_published(self):
        for field, value in (
            ("status", "missing"),
            ("relative_path", "audio/changed.wav"),
            ("byte_size", 1),
            ("sha256", "0" * 64),
            ("media_type", "audio/mpeg"),
        ):
            with self.subTest(field=field):
                interview = self.interview()
                asset_id, _path, _payload = self._registered_audio_asset()
                request_id, outcome = self._attach_while_write_lock_is_held(
                    interview["id"],
                    asset_id,
                    lambda: self.db.connection.execute(
                        f"UPDATE file_assets SET {field}=? WHERE id=?", (value, asset_id)
                    ),
                )
                self.assertIsInstance(outcome.get("error"), ApplicationError, outcome)
                self.assertEqual(outcome["error"].code, "INVALID_STATE")
                self.assert_no_published_audio(request_id)

    def _registered_audio_asset(self):
        asset_id = str(uuid.uuid4())
        relative = f"audio/{asset_id}.wav"
        path = self.root / "assets" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\0\0" * 1600)
        payload = buffer.getvalue()
        path.write_bytes(payload)
        self.service._insert(
            "file_assets", id=asset_id, kind="audio", status="ready",
            relative_path=relative, original_name="synthetic.wav",
            media_type="audio/wav", byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(), intent_json="{}",
            created_at=utc_now(), finalized_at=utc_now(),
        )
        return asset_id, path, payload


if __name__ == "__main__":
    unittest.main()
