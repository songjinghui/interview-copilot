"""Stage 2: durable manual import and query contracts, isolated storage only."""

import tempfile
import unittest
import uuid
from pathlib import Path

from tests.test_storage import feature
from interview_copilot.application import ApplicationError
from interview_copilot.storage import Database


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        module = feature(self, "interview_copilot.workbench")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite"
        self.db = Database(self.path)
        self.addCleanup(self.db.close)
        self.service = module.WorkbenchService(self.db)

    def command(self, name, expected=None, request_id=None, **fields):
        return self.service.execute(
            request_id or str(uuid.uuid4()), name, fields, expected_revision=expected
        )["data"]

    def job(self, **fields):
        return self.command(
            "ImportJob",
            text_fields={"title": "工程师", "company": "示例公司", **fields},
        )

    def test_manual_import_without_url_is_partial_and_replay_survives_reopen(self):
        request = str(uuid.uuid4())
        payload = {"text_fields": {"title": "工程师", "company": "示例公司"}}
        first = self.service.execute(request, "ImportJob", payload)
        with Database(self.path) as other:
            service = type(self.service)(other)
            self.assertEqual(first, service.execute(request, "ImportJob", payload))
            detail = service.query("jobs/" + first["data"]["id"])
            self.assertIsNone(detail["current_version"]["original_url"])
            self.assertEqual(detail["current_version"]["completeness"], "partial")
            self.assertEqual(detail["current_observation"]["method"], "manual")
            self.assertEqual(len(service.query("jobs")["items"]), 1)

    def test_unsafe_and_unknown_import_fields_are_rejected_without_rows(self):
        for fields in (
            {"url": "file:///C:/secret"},
            {"apply": True},
            {"locations": "北京"},
        ):
            with self.assertRaises(ApplicationError):
                self.job(**fields)
        with self.assertRaises(ApplicationError) as error:
            self.command("ImportJob", url="https://example.com/job")
        self.assertEqual(error.exception.code, "SOURCE_UNAVAILABLE")
        self.assertEqual(self.service.query("jobs")["items"], [])

    def test_profile_decodes_json_and_keeps_version_history(self):
        self.command(
            "SaveTarget",
            label="后端",
            criteria={"keywords": ["Python"], "any_city": True},
        )
        fact = self.command(
            "SaveFact",
            kind="skill",
            content={"title": "Python", "description": "本人补录"},
            provenance={"kind": "user"},
        )
        confirmed = self.command("ConfirmFact", fact["revision"], id=fact["id"])
        resume = self.command("ImportMaterial", label="简历", text="初版")
        self.command(
            "SaveMaterialVersion",
            material_id=resume["material_id"],
            parent_version_id=resume["id"],
            text="新版",
            fact_ids=[confirmed["id"]],
        )
        profile = self.service.query("profile")
        self.assertIs(profile["targets"][0]["active"], True)
        self.assertEqual(profile["targets"][0]["criteria"]["keywords"], ["Python"])
        self.assertEqual(profile["facts"][0]["status"], "confirmed")
        self.assertEqual(
            profile["materials"][0]["latest_version"]["text_content"], "新版"
        )
        versions = self.service.query(f"materials/{resume['material_id']}/versions")[
            "items"
        ]
        self.assertEqual([v["text_content"] for v in versions], ["新版", "初版"])

    def test_resume_conflict_reports_current_parent_without_exposing_text(self):
        resume = self.command("ImportMaterial", label="简历", text="private original")
        latest = self.command(
            "SaveMaterialVersion",
            material_id=resume["material_id"],
            parent_version_id=resume["id"],
            text="private current",
            fact_ids=[],
        )
        with self.assertRaises(ApplicationError) as error:
            self.command(
                "SaveMaterialVersion",
                material_id=resume["material_id"],
                parent_version_id=resume["id"],
                text="local draft",
                fact_ids=[],
            )
        self.assertEqual(error.exception.details.get("parent_version_id"), latest["id"])
        self.assertNotIn("private", str(error.exception.details))

    def test_opportunity_aggregate_preserves_confirmation_and_actual_result_separation(
        self,
    ):
        job = self.job(responsibilities="维护服务", requirements="Python")
        opportunity = self.command("SaveOpportunity", job_id=job["id"])
        prep = self.command(
            "SavePreparation",
            opportunity_id=opportunity["id"],
            job_version_id=job["current_version"]["id"],
            channel="官网",
            resume_exception="此渠道无需简历",
        )
        ready = self.command(
            "ConfirmPreparation",
            prep["revision"],
            preparation_id=prep["id"],
            step="materials",
        )
        detail = self.service.query("opportunities/" + opportunity["id"])
        self.assertEqual(detail["preparations"][0]["next_step"], "manual_apply")
        self.assertEqual(detail["applications"], [])
        app = self.command(
            "RecordApplication",
            opportunity_id=opportunity["id"],
            preparation_id=ready["id"],
            job_version_id=job["current_version"]["id"],
            channel="官网",
            outcome="unknown",
            evidence={"kind": "user_attestation", "statement": "尚未收到回执"},
        )
        self.assertEqual(
            self.service.query("applications/" + app["id"])["events"][0]["revision"], 1
        )
        self.assertEqual(
            len(
                self.service.query("opportunities/" + opportunity["id"])["applications"]
            ),
            1,
        )

    def test_pagination_is_bounded_filtered_and_rejects_wrong_query_cursor(self):
        for i in range(4):
            self.job(title=f"工程师 {i}")
        first = self.service.query("jobs", {"limit": "2"})
        second = self.service.query(
            "jobs", {"limit": "2", "cursor": first["next_cursor"]}
        )
        self.assertEqual(len(first["items"]) + len(second["items"]), 4)
        self.assertEqual(len({x["id"] for x in first["items"] + second["items"]}), 4)
        for params in (
            {"limit": "101"},
            {"cursor": "malformed"},
            {"cursor": first["next_cursor"], "query": "different"},
        ):
            with self.assertRaises(ApplicationError):
                self.service.query("jobs", params)
        self.assertEqual(
            len(self.service.query("jobs", {"query": "工程师 2"})["items"]), 1
        )
        self.assertEqual(self.service.query("sources")["items"], [])
        with self.assertRaises(ApplicationError):
            self.service.query("not-an-endpoint")
