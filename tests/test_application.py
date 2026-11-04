"""Command-level contracts; temporary databases, no HTTP or external actions."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from tests.test_storage import feature
from tests.test_job_store import make_record
from interview_copilot.jobs.store import SqliteJobStore


class ApplicationTest(unittest.TestCase):
    def setUp(self):
        self.storage = feature(self, "interview_copilot.storage")
        self.module = feature(self, "interview_copilot.application")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite"
        self.db = self.storage.Database(self.path)
        self.addCleanup(self.db.close)
        self.service = self.module.ApplicationService(self.db)
        self.jobs = SqliteJobStore(self.db)
        self.job = self.jobs.upsert(make_record())
        self.opportunity = self.command("SaveOpportunity", job_id=self.job.job_id)
        self.material = self.command(
            "ImportMaterial", label="Resume", text="Confirmed experience"
        )

    def command(self, command, expected=None, request_id=None, **fields):
        return self.service.execute(
            request_id or str(uuid.uuid4()), command, fields, expected_revision=expected
        )["data"]

    def prep(self, status="unknown", resume=True):
        if status != "unknown":
            self.command(
                "RecordCooldown",
                expected=self.opportunity["revision"],
                opportunity_id=self.opportunity["id"],
                scope="job",
                status=status,
                explanation="Recruiter statement",
                evidence={
                    "schema_version": 1,
                    "items": [
                        {"kind": "user", "text": "Recruiter explicitly stated this"}
                    ],
                },
            )
            self.opportunity = self.service.get_opportunity(self.opportunity["id"])
        return self.command(
            "SavePreparation",
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            resume_version_id=self.material["id"] if resume else None,
            resume_exception=(
                None if resume else "Online application requires no resume"
            ),
            channel="Company website",
            apply_url="https://example.com/apply",
        )

    def error(self, code, command, expected=None, **fields):
        with self.assertRaises(self.module.ApplicationError) as caught:
            self.command(command, expected, **fields)
        self.assertEqual(caught.exception.code, code)

    def test_present_requires_materials_then_cooldown_and_creates_no_application(self):
        prep = self.prep("present")
        self.error(
            "INVALID_STATE",
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="cooldown",
        )
        first = self.command(
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )
        self.assertEqual(first["next_step"], "cooldown")
        second = self.command(
            "ConfirmPreparation",
            first["revision"],
            preparation_id=prep["id"],
            step="cooldown",
        )
        self.assertEqual(second["status"], "ready_for_manual_apply")
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM applications").fetchone()[
                0
            ],
            0,
        )

    def test_absent_and_unknown_need_only_one_confirmation(self):
        for status in ("absent", "unknown"):
            with self.subTest(status=status):
                # Unknown is a fresh explicit correction after an absent note.
                if status == "unknown":
                    self.command(
                        "RecordCooldown",
                        self.opportunity["revision"],
                        opportunity_id=self.opportunity["id"],
                        scope="job",
                        status="unknown",
                        explanation="Needs verification",
                        evidence={"schema_version": 1, "items": []},
                    )
                prep = self.prep(status)
                confirmed = self.command(
                    "ConfirmPreparation",
                    prep["revision"],
                    preparation_id=prep["id"],
                    step="materials",
                )
                self.assertEqual(confirmed["next_step"], "manual_apply")
                self.assertIsNone(confirmed["cooldown_confirmed_at"])

    def test_preparation_reloads_exception_and_edits_reset_confirmations(self):
        prep = self.prep(resume=False)
        confirmed = self.command(
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )
        with self.storage.Database(self.path) as other:
            self.assertEqual(
                self.module.ApplicationService(other).get_preparation(prep["id"])[
                    "resume_exception"
                ],
                "Online application requires no resume",
            )
        updated = self.command(
            "SavePreparation",
            confirmed["revision"],
            id=prep["id"],
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            resume_version_id=None,
            resume_exception="Changed explanation",
            channel="Company website",
        )
        self.assertEqual(updated["status"], "draft")
        self.assertIsNone(updated["material_confirmed_at"])
        self.error(
            "VALIDATION",
            "ConfirmPreparation",
            updated["revision"],
            preparation_id=prep["id"],
            step="unexpected",
        )

    def test_missing_resume_and_explanation_cannot_confirm(self):
        # A draft may retain incomplete input; confirmation must reject it.
        prep = self.command(
            "SavePreparation",
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="Company website",
        )
        self.error(
            "VALIDATION",
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )

    def test_different_request_id_cannot_silently_reconfirm_completed_step(self):
        prep = self.prep()
        ready = self.command(
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )
        self.error(
            "INVALID_STATE",
            "ConfirmPreparation",
            ready["revision"],
            preparation_id=prep["id"],
            step="materials",
        )

    def test_idempotency_survives_restart_and_changed_body_is_rejected(self):
        request_id = str(uuid.uuid4())
        payload = {"label": "Fixed resume", "text": "Text"}
        first = self.service.execute(request_id, "ImportMaterial", payload)
        with self.storage.Database(self.path) as other:
            service = self.module.ApplicationService(other)
            self.assertEqual(
                service.execute(request_id, "ImportMaterial", payload), first
            )
            with self.assertRaises(self.module.ApplicationError) as caught:
                service.execute(
                    request_id, "ImportMaterial", {**payload, "text": "Changed"}
                )
            self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_stale_revision_rejected_without_erasing_current_input(self):
        prep = self.prep()
        ready = self.command(
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )
        self.error(
            "REVISION_CONFLICT",
            "DeferPreparation",
            prep["revision"],
            preparation_id=prep["id"],
        )
        self.assertEqual(
            self.service.get_preparation(prep["id"])["revision"], ready["revision"]
        )

    def test_material_revisions_pin_preparation_and_historical_application(self):
        prep = self.prep()
        application = self.command(
            "RecordApplication",
            opportunity_id=self.opportunity["id"],
            preparation_id=prep["id"],
            job_version_id=self.job.version_id,
            resume_version_id=self.material["id"],
            channel="Company website",
            outcome="submitted",
            submitted_at="2026-11-04T12:00:00+08:00",
            evidence={
                "schema_version": 1,
                "kind": "user_attestation",
                "statement": "I submitted",
                "asset_ids": [],
            },
        )
        new = self.command(
            "SaveMaterialVersion",
            material_id=self.material["material_id"],
            parent_version_id=self.material["id"],
            text="Revised resume",
            fact_ids=[],
        )
        self.assertNotEqual(new["id"], self.material["id"])
        self.assertEqual(
            self.service.get_application(application["id"])["resume_version_id"],
            self.material["id"],
        )
        self.assertEqual(
            self.service.get_preparation(prep["id"])["resume_version_id"],
            self.material["id"],
        )

    def test_resume_exception_snapshot_does_not_follow_later_preparation(self):
        prep = self.prep(resume=False)
        application = self.command(
            "RecordApplication",
            opportunity_id=self.opportunity["id"],
            preparation_id=prep["id"],
            job_version_id=self.job.version_id,
            channel="Company website",
            outcome="unknown",
            evidence={
                "schema_version": 1,
                "kind": "user_attestation",
                "statement": "Uncertain result",
                "asset_ids": [],
            },
        )
        self.command(
            "SavePreparation",
            prep["revision"],
            id=prep["id"],
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            resume_exception="Changed",
            channel="Company website",
        )
        history = self.service.get_application(application["id"])["events"]
        self.assertEqual(
            history[0]["snapshot"]["preparation"]["resume_exception"],
            "Online application requires no resume",
        )

    def test_history_can_be_added_without_preparation_but_submission_requires_evidence(
        self,
    ):
        fields = dict(
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="Manual",
            outcome="submitted",
            submitted_at="2026-11-04T12:00:00+08:00",
        )
        self.error("VALIDATION", "RecordApplication", **fields, evidence={})
        result = self.command(
            "RecordApplication",
            **fields,
            evidence={
                "schema_version": 1,
                "kind": "user_attestation",
                "statement": "Already applied elsewhere",
                "asset_ids": [],
            },
        )
        self.assertIsNone(result["preparation_id"])
        self.assertEqual(result["submitted_at"], "2026-11-04T04:00:00.000Z")

    def test_application_correction_appends_event_and_preserves_earlier_fact(self):
        evidence = {
            "schema_version": 1,
            "kind": "user_attestation",
            "statement": "Checking",
            "asset_ids": [],
        }
        row = self.command(
            "RecordApplication",
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="Manual",
            outcome="unknown",
            evidence=evidence,
        )
        self.command(
            "RecordApplication",
            row["revision"],
            id=row["id"],
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="Manual",
            outcome="submitted",
            submitted_at="2026-11-04T04:00:00Z",
            evidence=evidence,
            reason="Confirmed receipt",
        )
        history = self.service.get_application(row["id"])["events"]
        self.assertEqual(
            [event["snapshot"]["application"]["outcome"] for event in history],
            ["unknown", "submitted"],
        )

    def test_wrong_opportunity_job_and_unsafe_link_rejected(self):
        other = self.jobs.upsert(make_record(source_job_id="another"))
        self.error(
            "VALIDATION",
            "SavePreparation",
            opportunity_id=self.opportunity["id"],
            job_version_id=other.version_id,
            channel="Manual",
        )
        self.error(
            "VALIDATION",
            "SavePreparation",
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="Manual",
            apply_url="javascript:alert(1)",
        )

    def test_cooldown_update_invalidates_unused_confirmations(self):
        prep = self.prep()
        ready = self.command(
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )
        self.command(
            "RecordCooldown",
            self.opportunity["revision"],
            opportunity_id=self.opportunity["id"],
            scope="job",
            status="present",
            explanation="New statement",
            evidence={
                "schema_version": 1,
                "items": [{"kind": "user", "text": "Waiting required"}],
            },
        )
        latest = self.service.get_preparation(prep["id"])
        self.assertEqual(latest["status"], "draft")
        self.assertEqual(latest["cooldown_status"], "present")
        self.assertGreater(latest["revision"], ready["revision"])

    def test_material_facts_must_be_confirmed_and_snapshot_is_stable(self):
        fact = self.command(
            "SaveFact",
            kind="project",
            content={"title": "Project", "description": "I built it"},
            provenance={"kind": "user"},
        )
        self.error(
            "VALIDATION",
            "SaveMaterialVersion",
            material_id=self.material["material_id"],
            parent_version_id=self.material["id"],
            text="New",
            fact_ids=[fact["id"]],
        )
        confirmed = self.command("ConfirmFact", fact["revision"], id=fact["id"])
        version = self.command(
            "SaveMaterialVersion",
            material_id=self.material["material_id"],
            parent_version_id=self.material["id"],
            text="New",
            fact_ids=[fact["id"]],
        )
        self.command(
            "SaveFact",
            confirmed["revision"],
            id=fact["id"],
            kind="project",
            content={"title": "Changed", "description": "Other"},
            provenance={"kind": "user"},
        )
        self.assertEqual(
            version["fact_snapshot"]["facts"][0]["content"]["title"], "Project"
        )

    def test_receipt_failure_rolls_back_material_and_version(self):
        before = self.db.connection.execute(
            "SELECT count(*) FROM materials"
        ).fetchone()[0]
        self.db.connection.execute(
            "CREATE TEMP TRIGGER receipt_failure BEFORE INSERT ON command_receipts BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
        with self.assertRaises(self.module.ApplicationError):
            self.command("ImportMaterial", label="Must rollback", text="Not saved")
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM materials").fetchone()[0],
            before,
        )

    def test_concurrent_same_request_creates_one_material(self):
        request_id = str(uuid.uuid4())

        def submit(_):
            with self.storage.Database(self.path) as db:
                return self.module.ApplicationService(db).execute(
                    request_id,
                    "ImportMaterial",
                    {"label": "Concurrent", "text": "Same"},
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(
            self.db.connection.execute(
                "SELECT count(*) FROM materials WHERE label='Concurrent'"
            ).fetchone()[0],
            1,
        )

    def test_unknown_command_and_fields_are_rejected(self):
        self.error("UNKNOWN_COMMAND", "SubmitApplication")
        self.error(
            "VALIDATION", "SaveOpportunity", job_id=self.job.job_id, auto_submit=True
        )


if __name__ == "__main__":
    unittest.main()
