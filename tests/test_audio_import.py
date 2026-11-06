"""Automatic, durable ASR task creation for an already-stored local audio asset."""

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import uuid
import wave
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

from interview_copilot.application import ApplicationError
from interview_copilot.jobs.store import SqliteJobStore
from interview_copilot.storage import Database
from interview_copilot.storage.database import json_text, new_id, utc_now
from interview_copilot.workbench import WorkbenchService
from tests.test_job_store import make_record


class AudioImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database_path = self.root / "app.sqlite"
        self.db = Database(self.database_path)
        self.addCleanup(self.db.close)
        self.service = WorkbenchService(self.db)
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
        job = SqliteJobStore(self.db).upsert(make_record())
        opportunity = self.command("SaveOpportunity", job_id=job.job_id)
        interview = self.command(
            "SaveInterview",
            opportunity_id=opportunity["id"],
            label="面试",
            time_zone="Asia/Shanghai",
            starts_at="2026-11-20T10:00:00+08:00",
            ends_at="2026-11-20T11:00:00+08:00",
        )
        self.interview_id = interview["id"]

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

    def command(self, name, expected=None, request_id=None, **fields):
        return self.service.execute(
            request_id or str(uuid.uuid4()), name, fields, expected_revision=expected
        )["data"]

    def add_asset(self, *, interview_id=None, relative_path=None):
        identifier = new_id()
        relative_path = relative_path or f"audio/import/{identifier}.wav"
        path = self.root / "assets" / Path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(b"\x00\x00" * 1600)
        payload = buffer.getvalue()
        path.write_bytes(payload)
        now = utc_now()
        self.db.connection.execute(
            "INSERT INTO file_assets(id,kind,status,relative_path,original_name,media_type,byte_size,sha256,intent_json,created_at,finalized_at) VALUES(?, 'audio','ready',?,?,?,?,?,?,?,?)",
            (
                identifier,
                relative_path,
                "interview.wav",
                "audio/wav",
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                json_text({"operation_id": new_id(), "purpose": "audio_import"}),
                now,
                now,
            ),
        )
        return identifier, path, payload

    def test_attach_persists_audio_and_automatic_task_atomically_and_replays(self):
        asset_id, _path, _payload = self.add_asset()
        request_id = str(uuid.uuid4())
        first = self.command(
            "AttachAudioImport",
            request_id=request_id,
            interview_id=self.interview_id,
            asset_id=asset_id,
        )
        replay = self.service.execute(
            request_id,
            "AttachAudioImport",
            {"interview_id": self.interview_id, "asset_id": asset_id},
        )["data"]
        self.assertEqual(first, replay)
        audio = self.db.connection.execute(
            "SELECT * FROM audio_assets WHERE id=?", (first["audio_asset_id"],)
        ).fetchone()
        part = self.db.connection.execute(
            "SELECT * FROM audio_parts WHERE audio_asset_id=?", (audio["id"],)
        ).fetchone()
        task = self.db.connection.execute(
            "SELECT * FROM background_tasks WHERE id=?", (first["task_id"],)
        ).fetchone()
        transcription = self.db.connection.execute(
            "SELECT * FROM transcription_jobs WHERE task_id=?", (task["id"],)
        ).fetchone()
        self.assertEqual(audio["origin"], "import")
        self.assertEqual(audio["status"], "finalized")
        self.assertEqual(audio["completeness"], "complete")
        self.assertEqual(audio["duration_ms"], 100)
        self.assertEqual(part["file_asset_id"], asset_id)
        self.assertEqual(task["kind"], "transcribe")
        self.assertEqual(task["status"], "needs_attention")
        self.assertEqual(json.loads(task["last_error_json"])["code"], "MODEL_NOT_READY")
        self.assertEqual(transcription["audio_asset_id"], audio["id"])
        self.assertEqual(transcription["asset_revision"], 1)
        self.assertEqual(transcription["request_generation"], 1)
        self.assertEqual(first["task_id"], transcription["task_id"])
        detail = self.service.query("interviews/" + self.interview_id)
        self.assertEqual(detail["audio_assets"][0]["id"], audio["id"])
        self.assertEqual(
            detail["audio_assets"][0]["transcription"]["task_status"], "needs_attention"
        )
        self.assertEqual(
            self.db.connection.execute(
                "SELECT count(*) FROM audio_assets WHERE interview_id=?", (self.interview_id,)
            ).fetchone()[0],
            1,
        )
        with Database(self.database_path) as reopened:
            restored = WorkbenchService(reopened).query(
                "interviews/" + self.interview_id
            )
            self.assertEqual(restored["audio_assets"][0]["id"], audio["id"])
            self.assertEqual(
                restored["audio_assets"][0]["transcription"]["task_status"],
                "needs_attention",
            )

    def test_duplicate_attach_with_new_request_returns_same_audio_and_task(self):
        asset_id, _path, _payload = self.add_asset()
        first = self.command(
            "AttachAudioImport", interview_id=self.interview_id, asset_id=asset_id
        )
        second = self.command(
            "AttachAudioImport", interview_id=self.interview_id, asset_id=asset_id
        )
        self.assertEqual(first["audio_asset_id"], second["audio_asset_id"])
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM audio_assets").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM background_tasks").fetchone()[0],
            1,
        )

    def test_rejects_wrong_kind_missing_or_mutated_asset_and_cross_interview_reuse(self):
        audio_id, audio_path, _payload = self.add_asset()
        other_file = self.root / "assets/audio/not-audio.bin"
        other_file.parent.mkdir(parents=True, exist_ok=True)
        other_file.write_bytes(b"resume")
        resume_id = new_id()
        now = utc_now()
        self.db.connection.execute(
            "INSERT INTO file_assets(id,kind,status,relative_path,original_name,media_type,byte_size,sha256,intent_json,created_at,finalized_at) VALUES(?, 'resume','ready',?,?,?,?,?,?,?,?)",
            (resume_id, "audio/not-audio.bin", "x.bin", "application/octet-stream", 6,
             hashlib.sha256(b"resume").hexdigest(), "{}", now, now),
        )
        with self.assertRaises(ApplicationError):
            self.command("AttachAudioImport", interview_id=self.interview_id, asset_id=resume_id)

        audio_path.write_bytes(b"tampered")
        with self.assertRaises(ApplicationError):
            self.command("AttachAudioImport", interview_id=self.interview_id, asset_id=audio_id)

        malformed_id = new_id()
        malformed_path = self.root / "assets/audio/malformed.wav"
        malformed_path.parent.mkdir(parents=True, exist_ok=True)
        malformed_bytes = b"not a wave file"
        malformed_path.write_bytes(malformed_bytes)
        malformed_now = utc_now()
        self.db.connection.execute(
            "INSERT INTO file_assets(id,kind,status,relative_path,original_name,media_type,byte_size,sha256,intent_json,created_at,finalized_at) VALUES(?, 'audio','ready',?,?,?,?,?,?,?,?)",
            (
                malformed_id,
                "audio/malformed.wav",
                "malformed.wav",
                "audio/wav",
                len(malformed_bytes),
                hashlib.sha256(malformed_bytes).hexdigest(),
                "{}",
                malformed_now,
                malformed_now,
            ),
        )
        with self.assertRaises(ApplicationError):
            self.command(
                "AttachAudioImport", interview_id=self.interview_id, asset_id=malformed_id
            )
        self.db.connection.execute(
            "UPDATE file_assets SET status='missing' WHERE id=?", (audio_id,)
        )
        with self.assertRaises(ApplicationError):
            self.command("AttachAudioImport", interview_id=self.interview_id, asset_id=audio_id)

    def test_rejects_path_escape_and_asset_already_attached_to_another_interview(self):
        outside = self.root / "outside.wav"
        outside.write_bytes(b"outside")
        escaped_id = new_id()
        now = utc_now()
        self.db.connection.execute(
            "INSERT INTO file_assets(id,kind,status,relative_path,original_name,media_type,byte_size,sha256,intent_json,created_at,finalized_at) VALUES(?, 'audio','ready',?,?,?,?,?,?,?,?)",
            (escaped_id, "../outside.wav", "outside.wav", "audio/wav", 7,
             hashlib.sha256(b"outside").hexdigest(), "{}", now, now),
        )
        with self.assertRaises(ApplicationError):
            self.command("AttachAudioImport", interview_id=self.interview_id, asset_id=escaped_id)

        asset_id, _path, _payload = self.add_asset()
        first = self.command(
            "AttachAudioImport", interview_id=self.interview_id, asset_id=asset_id
        )
        other_opportunity = self.command(
            "SaveOpportunity", title="另一机会", company_name="另一机会"
        )
        other_interview = self.command(
            "SaveInterview",
            opportunity_id=other_opportunity["id"],
            label="第二场",
            time_zone="UTC",
            starts_at="2026-11-21T10:00:00+00:00",
        )
        with self.assertRaises(ApplicationError):
            self.command(
                "AttachAudioImport",
                interview_id=other_interview["id"],
                asset_id=asset_id,
            )
        self.assertTrue(
            self.db.connection.execute(
                "SELECT 1 FROM audio_assets WHERE id=?", (first["audio_asset_id"],)
            ).fetchone()
        )

    def test_failure_after_audio_insert_rolls_back_asset_link_and_task(self):
        asset_id, _path, _payload = self.add_asset()
        original_insert = self.service._insert

        def fail_transcription_insert(table, **fields):
            if table == "transcription_jobs":
                raise sqlite3.IntegrityError("simulated final transaction write failure")
            return original_insert(table, **fields)

        with patch.object(self.service, "_insert", side_effect=fail_transcription_insert):
            with self.assertRaises(ApplicationError) as error:
                self.command(
                    "AttachAudioImport", interview_id=self.interview_id, asset_id=asset_id
                )
        self.assertEqual(error.exception.code, "STORAGE_CONSTRAINT")
        for table in ("audio_assets", "audio_parts", "background_tasks", "transcription_jobs"):
            self.assertEqual(
                self.db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
                0,
                table,
            )

    def test_file_replaced_after_preflight_is_rejected(self):
        asset_id, path, payload = self.add_asset()
        original_prepare = self.service.prepare_command

        def replace_after_preflight(command, fields):
            prepared = original_prepare(command, fields)
            path.write_bytes(b"x" * len(payload))
            return prepared

        with patch.object(self.service, "prepare_command", side_effect=replace_after_preflight):
            with self.assertRaises(ApplicationError):
                self.command(
                    "AttachAudioImport", interview_id=self.interview_id, asset_id=asset_id
                )
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM audio_assets").fetchone()[0], 0
        )

    def test_asset_metadata_change_after_preflight_is_rejected(self):
        mutations = (
            ("status", "missing"),
            ("relative_path", "audio/renamed.wav"),
            ("byte_size", 1),
            ("sha256", "0" * 64),
            ("media_type", "audio/mpeg"),
        )
        for column, changed_value in mutations:
            with self.subTest(column=column):
                asset_id, _path, _payload = self.add_asset()
                original_value = self.db.connection.execute(
                    f"SELECT {column} FROM file_assets WHERE id=?", (asset_id,)
                ).fetchone()[0]
                original_prepare = self.service.prepare_command
                mutation = {"column": column, "value": changed_value}

                def change_asset_after_preflight(command, fields):
                    prepared = original_prepare(command, fields)
                    self.db.connection.execute(
                        f"UPDATE file_assets SET {mutation['column']}=? WHERE id=?",
                        (mutation["value"], asset_id),
                    )
                    return prepared

                with patch.object(
                    self.service, "prepare_command", side_effect=change_asset_after_preflight
                ):
                    with self.assertRaises(ApplicationError):
                        self.command(
                            "AttachAudioImport",
                            interview_id=self.interview_id,
                            asset_id=asset_id,
                        )
                self.assertEqual(
                    self.db.connection.execute(
                        "SELECT count(*) FROM audio_assets"
                    ).fetchone()[0],
                    0,
                )
                self.db.connection.execute(
                    f"UPDATE file_assets SET {column}=? WHERE id=?",
                    (original_value, asset_id),
                )


if __name__ == "__main__":
    unittest.main()
