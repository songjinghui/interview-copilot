"""Cross-command regressions from the independent review of dae96d5."""

import unittest
from tests import test_application
from tests.test_job_store import make_record


class ReviewRegressionTest(unittest.TestCase):
    setUp = test_application.ApplicationTest.setUp
    command = test_application.ApplicationTest.command
    prep = test_application.ApplicationTest.prep
    error = test_application.ApplicationTest.error

    def record(self, preparation, **overrides):
        fields = dict(
            opportunity_id=self.opportunity["id"],
            preparation_id=preparation["id"],
            job_version_id=self.job.version_id,
            resume_version_id=preparation["resume_version_id"],
            channel="Company website",
            outcome="unknown",
            evidence={"kind": "user_attestation", "statement": "Checking receipt"},
        )
        fields.update(overrides)
        return self.command("RecordApplication", **fields)

    def correct(self, application, **overrides):
        # Keeping the association implicit and explicitly repeating its ID must
        # both retain the historical snapshot. A changed ID is a deliberate edit.
        fields = dict(
            id=application["id"],
            opportunity_id=application["opportunity_id"],
            job_version_id=application["job_version_id"],
            resume_version_id=application["resume_version_id"],
            channel=application["channel"],
            outcome="submitted",
            submitted_at="2026-11-04T04:00:00Z",
            evidence={"kind": "user_attestation", "statement": "Receipt checked"},
            reason="Correct the historical result",
        )
        fields.update(overrides)
        return self.command("RecordApplication", application["revision"], **fields)

    def confirm(self, preparation, step="materials"):
        return self.command(
            "ConfirmPreparation",
            preparation["revision"],
            preparation_id=preparation["id"],
            step=step,
        )

    def unlink(self):
        opportunity = self.service.get_opportunity(self.opportunity["id"])
        return self.command(
            "UnlinkJob",
            opportunity["revision"],
            opportunity_id=opportunity["id"],
            job_id=self.job.job_id,
            basis={"kind": "user_confirmed", "description": "A different role"},
        )

    def reopen(self):
        self.db.close()
        self.db = self.storage.Database(self.path)
        self.addCleanup(self.db.close)
        self.service = self.module.ApplicationService(self.db)

    def test_result_corrections_keep_original_snapshot_across_edits_and_restart(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                preparation = self.confirm(self.prep(resume=resume))
                original = self.record(preparation)
                snapshot = original["events"][0]["snapshot"]["preparation"]
                self.command(
                    "SavePreparation",
                    preparation["revision"],
                    id=preparation["id"],
                    opportunity_id=self.opportunity["id"],
                    job_version_id=self.job.version_id,
                    resume_exception="Future application explanation",
                    channel="A later channel",
                )
                corrected = self.correct(original)
                self.reopen()
                repeated = self.correct(
                    corrected,
                    preparation_id=preparation["id"],
                    submitted_at="2026-11-04T05:00:00Z",
                )
                self.assertEqual(len(repeated["events"]), 3)
                for event in repeated["events"]:
                    self.assertEqual(event["snapshot"]["preparation"], snapshot)
                self.assertEqual(repeated["events"][0], original["events"][0])

    def test_explicit_reassociation_freezes_new_snapshot_for_later_corrections(self):
        original = self.record(self.prep(resume=False))
        replacement = self.confirm(self.prep())
        reassociated = self.correct(original, preparation_id=replacement["id"])
        self.command(
            "SavePreparation",
            replacement["revision"],
            id=replacement["id"],
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            resume_exception="Edited after the correction",
            channel="Later",
        )
        corrected = self.correct(reassociated)
        self.assertEqual(
            corrected["events"][-1]["snapshot"]["preparation"], replacement
        )
        self.assertEqual(corrected["events"][0], original["events"][0])
        detached = self.correct(corrected, preparation_id=None)
        self.assertIsNone(detached["events"][-1]["snapshot"]["preparation"])
        self.assertIsNone(
            self.correct(detached)["events"][-1]["snapshot"]["preparation"]
        )

    def test_reassociation_to_another_opportunity_is_rejected_without_event(self):
        original = self.record(self.prep())
        other_job = self.jobs.upsert(make_record(source_job_id="another"))
        other_opportunity = self.command("SaveOpportunity", job_id=other_job.job_id)
        other = self.command(
            "SavePreparation",
            opportunity_id=other_opportunity["id"],
            job_version_id=other_job.version_id,
            resume_version_id=self.material["id"],
            channel="Other",
        )
        with self.assertRaises(self.module.ApplicationError) as error:
            self.correct(original, preparation_id=other["id"])
        self.assertEqual(error.exception.code, "VALIDATION")
        self.assertEqual(self.service.get_application(original["id"]), original)

    def test_unlink_invalidates_draft_partial_ready_and_deferred_preparations(self):
        draft = self.prep("present")
        partial = self.confirm(self.prep())
        ready = self.confirm(self.confirm(self.prep()), "cooldown")
        deferred = self.command(
            "DeferPreparation",
            draft["revision"],
            preparation_id=draft["id"],
        )
        draft = self.prep()
        self.unlink()
        for prior in (draft, partial, ready, deferred):
            with self.subTest(state=prior["next_step"]):
                refreshed = self.service.get_preparation(prior["id"])
                self.assertEqual(refreshed["revision"], prior["revision"] + 1)
                self.assertIsNone(refreshed["material_confirmed_at"])
                self.assertIsNone(refreshed["cooldown_confirmed_at"])
                self.assertNotEqual(refreshed["status"], "ready_for_manual_apply")
                self.assertEqual(refreshed["next_step"], "relink_job")
                self.error(
                    "REVISION_CONFLICT",
                    "ConfirmPreparation",
                    prior["revision"],
                    preparation_id=prior["id"],
                    step="materials",
                )

    def test_fresh_revision_and_restart_cannot_confirm_an_unlinked_job(self):
        preparation = self.prep()
        self.unlink()
        self.reopen()
        refreshed = self.service.get_preparation(preparation["id"])
        self.error(
            "VALIDATION",
            "ConfirmPreparation",
            refreshed["revision"],
            preparation_id=refreshed["id"],
            step="materials",
        )

    def test_relink_requires_confirmation_again_without_extra_cooldown_step(self):
        ready = self.confirm(self.prep())
        self.unlink()
        opportunity = self.service.get_opportunity(self.opportunity["id"])
        self.command(
            "LinkJob",
            opportunity["revision"],
            opportunity_id=opportunity["id"],
            job_id=self.job.job_id,
            basis={"kind": "user_confirmed", "description": "Verified the association"},
        )
        refreshed = self.service.get_preparation(ready["id"])
        self.assertEqual(refreshed["next_step"], "materials")
        self.assertEqual(self.confirm(refreshed)["next_step"], "manual_apply")

    def test_unlink_preserves_history_and_allows_correction_of_existing_application(
        self,
    ):
        preparation = self.confirm(self.prep())
        original = self.record(preparation)
        self.unlink()
        self.assertEqual(self.service.get_application(original["id"]), original)
        corrected = self.correct(original)
        self.assertEqual(
            corrected["events"][-1]["snapshot"]["preparation"],
            original["events"][0]["snapshot"]["preparation"],
        )
        self.assertEqual(corrected["events"][0], original["events"][0])
        self.assertEqual(
            self.service.get_opportunity(self.opportunity["id"])["job_ids"], []
        )
        self.assertEqual(
            self.service.get_preparation(preparation["id"])["next_step"], "relink_job"
        )

    def test_correction_cannot_introduce_an_unlinked_job(self):
        original = self.record(self.prep())
        other_job = self.jobs.upsert(make_record(source_job_id="unlinked"))
        with self.assertRaises(self.module.ApplicationError) as error:
            self.correct(original, job_version_id=other_job.version_id)
        self.assertEqual(error.exception.code, "VALIDATION")
        self.assertEqual(self.service.get_application(original["id"]), original)

    def test_unlink_only_invalidates_preparations_for_the_removed_job(self):
        self.prep()
        other_job = self.jobs.upsert(make_record(source_job_id="retained"))
        opportunity = self.service.get_opportunity(self.opportunity["id"])
        self.command(
            "LinkJob",
            opportunity["revision"],
            opportunity_id=opportunity["id"],
            job_id=other_job.job_id,
            basis={"kind": "user_confirmed", "description": "Another source"},
        )
        other = self.confirm(
            self.command(
                "SavePreparation",
                opportunity_id=opportunity["id"],
                job_version_id=other_job.version_id,
                resume_version_id=self.material["id"],
                channel="Other",
            )
        )
        self.unlink()
        self.assertEqual(self.service.get_preparation(other["id"]), other)

    def test_receipt_failure_rolls_back_unlink_and_preparation_invalidation(self):
        preparation = self.confirm(self.prep())
        self.db.connection.execute(
            "CREATE TEMP TRIGGER reject_receipt BEFORE INSERT ON command_receipts BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
        with self.assertRaises(self.module.ApplicationError) as error:
            self.unlink()
        self.assertEqual(error.exception.code, "STORAGE_CONSTRAINT")
        self.assertEqual(self.service.get_preparation(preparation["id"]), preparation)
        self.assertEqual(
            self.service.get_opportunity(self.opportunity["id"])["job_ids"],
            [self.job.job_id],
        )


if __name__ == "__main__":
    unittest.main()
