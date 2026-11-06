"""Reviewer probes; run with an explicit feature checkout, isolated data only.

python -X utf8 docs/review-probes/phase3-service-2026-11-06.py PATH_TO_CHECKOUT
These assertions describe required behavior and fail on the reviewed snapshot.
"""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from datetime import timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
import wave
from zoneinfo import ZoneInfoNotFoundError

checkout = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(checkout / "src"))
from fastapi.testclient import TestClient
from interview_copilot.application import ApplicationError
from interview_copilot.http import create_app
from interview_copilot.session import Sessions
from interview_copilot.storage import Database
from interview_copilot.storage.database import utc_now
from interview_copilot.workbench import WorkbenchService


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase3-review-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "app.sqlite"
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.service = WorkbenchService(self.db)
        self.opp = self.command("SaveOpportunity", title="Synthetic", company_name="Review")

    def command(self, name, expected=None, **payload):
        return self.service.execute(
            str(uuid4()), name, payload, expected_revision=expected
        )["data"]

    def interview(self, **changes):
        payload = dict(
            opportunity_id=self.opp["id"], label="Synthetic interview",
            starts_at="2030-11-20T10:00:00+08:00",
            ends_at="2030-11-20T11:00:00+08:00",
            time_zone="Asia/Shanghai", format="online", status="planned",
            reminder_offsets=[60],
        )
        payload.update(changes)
        return self.command("SaveInterview", **payload)

    def client(self):
        sessions = Sessions(b"isolated-review-key" * 3)
        origin = "http://127.0.0.1:17863"
        app = create_app(self.path, sessions)
        token = sessions.exchange(sessions.bootstrap())
        client = TestClient(app, base_url=origin)
        self.addCleanup(client.close)
        headers = {"Authorization": "Bearer " + token, "Origin": origin}
        return client, headers

    def test_A1_existing_opportunity_filter_vocabulary(self):
        client, headers = self.client()
        results = {}
        for status in (
            "saved", "deferred", "applying", "applied", "interviewing",
            "offer", "rejected", "withdrawn", "archived",
        ):
            self.opp = self.command(
                "UpdateOpportunity", expected=self.opp["revision"],
                id=self.opp["id"], status=status,
            )
            response = client.get("/api/v1/opportunities?status=" + status, headers=headers)
            results[status] = response.status_code
        self.assertEqual(results, dict.fromkeys(results, 200))

    def test_A2_unknown_zone_must_not_silently_schedule(self):
        # Simulate a resolver with a known valid zone, isolating "unknown zone"
        # from "no tzdb on this Windows host". No new dependency is installed.
        def resolver(name):
            if name == "Asia/Shanghai":
                return timezone(timedelta(hours=8))
            raise ZoneInfoNotFoundError(name)
        with patch("interview_copilot.workbench.ZoneInfo", side_effect=resolver):
            self.interview()
            with self.assertRaises(ApplicationError):
                self.interview(time_zone="Not/A_Real_Zone")

    def test_A3_UTC_query_times_roundtrip_with_display_zone(self):
        with patch(
            "interview_copilot.workbench.ZoneInfo",
            return_value=timezone(timedelta(hours=8)),
        ):
            created = self.interview()
            view = self.service.query("interviews/" + created["id"])["schedule"]
            self.assertEqual(view["starts_at"], "2030-11-20T02:00:00.000Z")
            try:
                updated = self.command(
                    "SaveInterview", expected=view["revision"], id=view["id"],
                    opportunity_id=view["opportunity_id"], label="Label correction",
                    starts_at=view["starts_at"], ends_at=view["ends_at"],
                    time_zone=view["time_zone"], format=view["format"],
                    status=view["status"], reminder_offsets=[60],
                )
            except ApplicationError as error:
                self.fail(f"Rejected own canonical UTC query fields: {error.code}: {error}")
            self.assertEqual(updated["starts_at"], view["starts_at"])

    def test_A4_slow_audio_validation_does_not_block_profile_query(self):
        interview = self.interview()
        asset_id = str(uuid4())
        relative = f"audio/{asset_id}.wav"
        file = self.root / "assets" / relative
        file.parent.mkdir(parents=True)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(16000)
            writer.writeframes(b"\0\0" * 1600)
        payload = buf.getvalue()
        file.write_bytes(payload)
        self.service._insert(
            "file_assets", id=asset_id, kind="audio", status="ready",
            relative_path=relative, original_name="synthetic.wav",
            media_type="audio/wav", byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(), intent_json="{}",
            created_at=utc_now(), finalized_at=utc_now(),
        )
        client, headers = self.client()
        entered, release = threading.Event(), threading.Event()
        errors = []
        original = WorkbenchService._audio_file

        def delayed(service, asset):
            entered.set()
            if not release.wait(12):
                raise RuntimeError("review probe timed out")
            return original(service, asset)

        def attach():
            try:
                with Database(self.path) as db:
                    WorkbenchService(db).execute(
                        str(uuid4()), "AttachAudioImport",
                        {"interview_id": interview["id"], "asset_id": asset_id},
                    )
            except BaseException as error:
                errors.append(error)

        with patch.object(WorkbenchService, "_audio_file", delayed):
            worker = threading.Thread(target=attach)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                response = client.get("/api/v1/profile", headers=headers)
            finally:
                release.set()
                worker.join(15)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

