"""Reject malformed structured evidence before it becomes a durable fact."""

import json
import unittest
from tests import test_application


class ValidationTest(unittest.TestCase):
    setUp = test_application.ApplicationTest.setUp
    command = test_application.ApplicationTest.command
    error = test_application.ApplicationTest.error

    def test_nested_unknown_fields_and_future_schema_are_rejected(self):
        for content in (
            {"title": "T", "description": "D", "invented_fact": True},
            {"schema_version": 2, "title": "T", "description": "D"},
        ):
            with self.subTest(content=content):
                self.error(
                    "VALIDATION",
                    "SaveFact",
                    kind="project",
                    content=content,
                    provenance={"kind": "user"},
                )
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM profile_facts").fetchone()[
                0
            ],
            0,
        )

    def test_extracted_fact_requires_existing_material_and_exact_quote(self):
        for provenance in (
            {"kind": "material_extract"},
            {
                "kind": "material_extract",
                "material_version_id": self.material["id"],
                "quote": "Not in this resume",
            },
        ):
            with self.subTest(provenance=provenance):
                self.error(
                    "VALIDATION",
                    "SaveFact",
                    kind="project",
                    content={"title": "T", "description": "D"},
                    provenance=provenance,
                )
        fact = self.command(
            "SaveFact",
            kind="project",
            content={"title": "T", "description": "D"},
            provenance={
                "kind": "material_extract",
                "material_version_id": self.material["id"],
                "quote": "Confirmed experience",
            },
        )
        self.assertEqual(fact["status"], "draft")

    def test_invalid_dates_and_non_uuid_references_are_rejected(self):
        with self.subTest(field="date"):
            self.error(
                "VALIDATION",
                "SaveFact",
                kind="employment",
                content={"title": "T", "description": "D", "start_date": "2026-02-30"},
                provenance={"kind": "user"},
            )
        with self.subTest(field="uuid"):
            self.error("VALIDATION", "SaveOpportunity", job_id="not-a-uuid")

    def test_conditions_validate_money_and_importance_before_saving(self):
        criteria = {"keywords": ["Engineer"], "any_city": True, "conditions": []}
        for condition in (
            "not an object",
            {
                "field": "salary",
                "operator": "gte",
                "value": 10000,
                "importance": "must",
            },
            {
                "field": "salary",
                "operator": "gte",
                "value": {"amount": 10000, "currency": "CNY", "period": "month"},
                "importance": "maybe",
            },
        ):
            with self.subTest(condition=condition):
                self.error(
                    "VALIDATION",
                    "SaveTarget",
                    label="Target",
                    criteria={**criteria, "conditions": [condition]},
                )
        target = self.command(
            "SaveTarget",
            label="Target",
            criteria={
                **criteria,
                "conditions": [
                    {
                        "field": "salary",
                        "operator": "gte",
                        "value": {
                            "amount": 10000,
                            "currency": "CNY",
                            "period": "month",
                        },
                        "importance": "must",
                    }
                ],
            },
        )
        self.assertEqual(json.loads(target["criteria_json"])["schema_version"], 1)

    def test_cooldown_evidence_cannot_smuggle_unsafe_url_or_unknown_kind(self):
        for item in (
            {"kind": "url", "text": "Policy", "url": "javascript:alert(1)"},
            {"kind": "guess", "text": "Model guessed"},
        ):
            with self.subTest(item=item):
                revision = self.service.get_opportunity(self.opportunity["id"])[
                    "revision"
                ]
                self.error(
                    "VALIDATION",
                    "RecordCooldown",
                    revision,
                    opportunity_id=self.opportunity["id"],
                    scope="job",
                    status="present",
                    explanation="Rule",
                    evidence={"items": [item]},
                )
        self.assertEqual(
            self.db.connection.execute(
                "SELECT count(*) FROM cooldown_notes"
            ).fetchone()[0],
            0,
        )

    def test_unlink_requires_user_basis_and_preserves_saved_jd(self):
        fields = dict(opportunity_id=self.opportunity["id"], job_id=self.job.job_id)
        self.error(
            "VALIDATION",
            "UnlinkJob",
            self.opportunity["revision"],
            **fields,
            basis={"kind": "guessed"},
        )
        result = self.command(
            "UnlinkJob",
            self.opportunity["revision"],
            **fields,
            basis={"kind": "user_confirmed", "description": "Different role"},
        )
        self.assertEqual(result["job_ids"], [])
        self.assertEqual(
            self.db.connection.execute("SELECT count(*) FROM job_versions").fetchone()[
                0
            ],
            1,
        )

    def test_application_evidence_unknown_fields_are_rejected(self):
        self.error(
            "VALIDATION",
            "RecordApplication",
            opportunity_id=self.opportunity["id"],
            job_version_id=self.job.version_id,
            channel="web",
            outcome="unknown",
            evidence={
                "kind": "user_attestation",
                "statement": "Uncertain",
                "auto_submit": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
