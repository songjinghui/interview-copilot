"""Interview scheduling and reminder persistence, using isolated databases only."""

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta, timezone
from zoneinfo import ZoneInfoNotFoundError

from interview_copilot.application import ApplicationError
from interview_copilot.jobs.store import SqliteJobStore
from interview_copilot.storage import Database
from interview_copilot.workbench import WorkbenchService
from tests.test_job_store import make_record


class InterviewScheduleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "interviews.sqlite"
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.service = WorkbenchService(self.db)
        self.job = SqliteJobStore(self.db).upsert(make_record())
        self.opportunity = self.command("SaveOpportunity", job_id=self.job.job_id)
        self.other_opportunity = self.command(
            "SaveOpportunity", title="另一家公司", company_name="另一家公司"
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

    def command(self, name, expected=None, request_id=None, **fields):
        return self.service.execute(
            request_id or str(uuid.uuid4()), name, fields, expected_revision=expected
        )["data"]

    def interview(self, **overrides):
        values = {
            "opportunity_id": self.opportunity["id"],
            "label": "技术一面",
            "starts_at": "2026-11-10T10:00:00+08:00",
            "ends_at": "2026-11-10T11:00:00+08:00",
            "time_zone": "Asia/Shanghai",
            "format": "online",
            "location": "视频会议",
            "reminder_offsets": [1440, 60],
        }
        values.update(overrides)
        return self.command("SaveInterview", **values)

    def test_create_normalizes_times_persists_reminders_and_is_idempotent(self):
        request_id = str(uuid.uuid4())
        values = {
            "opportunity_id": self.opportunity["id"],
            "label": "技术一面",
            "starts_at": "2026-11-10T10:00:00+08:00",
            "ends_at": "2026-11-10T11:00:00+08:00",
            "time_zone": "Asia/Shanghai",
            "format": "online",
            "reminder_offsets": [1440, 60],
        }
        first = self.command("SaveInterview", request_id=request_id, **values)
        with Database(self.path) as reopened:
            service = WorkbenchService(reopened)
            replay = service.execute(request_id, "SaveInterview", values)["data"]
            self.assertEqual(first, replay)
            reminders = reopened.connection.execute(
                "SELECT id,scheduled_for,status FROM reminders WHERE interview_id=? ORDER BY scheduled_for,id",
                (first["id"],),
            ).fetchall()
            self.assertEqual(
                [(r["scheduled_for"], r["status"]) for r in reminders],
                [
                    ("2026-11-09T02:00:00.000Z", "pending"),
                    ("2026-11-10T01:00:00.000Z", "pending"),
                ],
            )
            self.assertEqual(first["starts_at"], "2026-11-10T02:00:00.000Z")
            self.assertEqual(first["reminder_ids"], [r["id"] for r in reminders])

    def test_unknown_time_allows_past_interview_but_cannot_schedule_offsets(self):
        past = self.interview(
            label="历史补录",
            starts_at=None,
            ends_at=None,
            reminder_offsets=[],
            status="completed",
        )
        self.assertEqual(past["status"], "completed")
        self.assertIsNone(past["starts_at"])
        with self.assertRaises(ApplicationError) as error:
            self.interview(starts_at=None, reminder_offsets=[])
        self.assertEqual(error.exception.code, "VALIDATION")

    def test_completed_or_cancelled_interviews_do_not_create_pending_reminders(self):
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                interview = self.interview(status=status)
                self.assertEqual(interview["reminder_ids"], [])
                self.assertEqual(interview["status"], status)

    def test_already_due_reminder_is_not_left_pending_without_delivery_worker(self):
        interview = self.interview(
            starts_at="2026-11-05T10:00:00+08:00",
            ends_at="2026-11-05T11:00:00+08:00",
            reminder_offsets=[10],
        )
        reminder = self.db.connection.execute(
            "SELECT status FROM reminders WHERE id=?", (interview["reminder_ids"][0],)
        ).fetchone()
        self.assertEqual(reminder["status"], "missed")

    def test_rejects_invalid_timezone_range_and_cross_opportunity_application(self):
        application = self.command(
            "RecordApplication",
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="官网",
            outcome="unknown",
            evidence={"kind": "user_attestation", "statement": "待确认"},
        )
        invalid = (
            {"time_zone": "Not a zone"},
            {"ends_at": "2026-11-10T09:00:00+08:00"},
            {"starts_at": "2026-11-10T10:00:00"},
            {"reminder_offsets": [-1]},
            {"format": "unknown-format"},
            {"application_id": str(uuid.uuid4())},
            {"opportunity_id": self.other_opportunity["id"], "application_id": application["id"]},
        )
        for override in invalid:
            with self.subTest(override=override), self.assertRaises(ApplicationError):
                self.interview(**override)

    def test_revision_rebuilds_pending_reminders_and_preserves_delivered_history(self):
        created = self.interview()
        first_reminder = created["reminder_ids"][0]
        self.db.connection.execute(
            "UPDATE reminders SET status='delivered',delivered_at='2026-11-08T00:00:00.000Z' WHERE id=?",
            (first_reminder,),
        )
        updated = self.command(
            "SaveInterview",
            expected=created["revision"],
            id=created["id"],
            opportunity_id=self.opportunity["id"],
            label="技术二面",
            starts_at="2026-11-11T10:00:00+08:00",
            ends_at="2026-11-11T11:00:00+08:00",
            time_zone="Asia/Shanghai",
            format="online",
            location=None,
            status="planned",
            reminder_offsets=[30],
        )
        rows = self.db.connection.execute(
            "SELECT id,scheduled_for,status FROM reminders WHERE interview_id=? ORDER BY rowid",
            (created["id"],),
        ).fetchall()
        self.assertEqual(updated["revision"], created["revision"] + 1)
        self.assertEqual(rows[0]["status"], "delivered")
        self.assertEqual(rows[1]["status"], "cancelled")
        self.assertEqual(rows[2]["status"], "pending")
        self.assertEqual(rows[2]["scheduled_for"], "2026-11-11T01:30:00.000Z")
        with self.assertRaises(ApplicationError) as error:
            self.command(
                "SaveInterview",
                expected=created["revision"],
                id=created["id"],
                opportunity_id=self.opportunity["id"],
                label="过期写入",
                starts_at="2026-11-12T10:00:00+08:00",
                ends_at="2026-11-12T11:00:00+08:00",
                time_zone="Asia/Shanghai",
                format="online",
                status="planned",
                reminder_offsets=[],
            )
        self.assertEqual(error.exception.code, "REVISION_CONFLICT")

    def test_acknowledge_reminder_is_idempotent_and_queries_include_schedule(self):
        interview = self.interview(reminder_offsets=[60])
        reminder_id = interview["reminder_ids"][0]
        first = self.command("AcknowledgeReminder", reminder_id=reminder_id)
        second = self.command("AcknowledgeReminder", reminder_id=reminder_id)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "acknowledged")
        detail = self.service.query("interviews/" + interview["id"])
        self.assertEqual(detail["schedule"]["id"], interview["id"])
        self.assertIsNone(detail["current_context"])
        self.assertEqual(detail["reminders"][0]["status"], "acknowledged")
        page = self.service.query("interviews", {"status": "planned"})
        self.assertEqual([row["schedule"]["id"] for row in page["items"]], [interview["id"]])
        reminders = self.service.query("reminders", {"status": "acknowledged"})
        self.assertEqual(reminders["items"][0]["interview"]["id"], interview["id"])
        with self.assertRaises(ApplicationError):
            self.service.query("interviews", {"from": "2026-11-11T00:00:00Z", "to": "2026-11-10T00:00:00Z"})
        self.assertEqual(
            self.service.query("opportunities/" + self.opportunity["id"])["interviews"][0]["schedule"]["id"],
            interview["id"],
        )


if __name__ == "__main__":
    unittest.main()
