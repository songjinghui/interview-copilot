"""Same-origin API contracts; ASGI client, temporary database and test secrets."""

import tempfile
import unittest
import uuid
from datetime import timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError
from pathlib import Path
from fastapi.testclient import TestClient
from tests.test_storage import feature


class HttpTest(unittest.TestCase):
    def setUp(self):
        module = feature(self, "interview_copilot.http")
        session = feature(self, "interview_copilot.session")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        static = root / "ui"
        static.mkdir()
        (static / "index.html").write_text("<html><main>Workbench</main></html>")
        (root / "secret.txt").write_text("never serve")
        self.sessions = session.Sessions(b"test-only-key" * 4)
        self.origin = "http://127.0.0.1:17863"
        self.app = module.create_app(
            root / "data.sqlite", self.sessions, port=17863, static_dir=static
        )
        self.client = TestClient(self.app, base_url=self.origin)
        self.addCleanup(self.client.close)
        response = self.client.post(
            "/session/exchange",
            json={"nonce": self.sessions.bootstrap()},
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.token = response.json()["token"]
        self.headers = {"Authorization": "Bearer " + self.token, "Origin": self.origin}
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

    def command(self, name, fields, revision=None, request=None):
        return self.client.post(
            "/api/v1/commands",
            headers=self.headers,
            json={
                "command": name,
                "request_id": request or str(uuid.uuid4()),
                "input": fields,
                "expected_revision": revision,
            },
        )

    def test_auth_host_origin_and_sensitive_error_boundaries(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/profile").status_code, 401)
        self.assertEqual(
            self.client.get(
                "/health", headers={"Host": "attacker.example"}
            ).status_code,
            403,
        )
        for origin in ("https://evil.example", "null", "http://127.0.0.1:18888"):
            self.assertEqual(
                self.client.post(
                    "/session/exchange",
                    json={"nonce": self.sessions.bootstrap()},
                    headers={"Origin": origin},
                ).status_code,
                403,
            )
        self.assertEqual(
            self.client.post(
                "/session/renew", headers={"Authorization": "Bearer " + self.token}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/session/renew", headers=self.headers, json={}
            ).status_code,
            200,
        )
        root = self.client.get("/")
        self.assertIn("script-src 'self'", root.headers["Content-Security-Policy"])
        self.assertIn("no-store", root.headers["Cache-Control"])
        self.assertNotIn("never serve", self.client.get("/%2e%2e/secret.txt").text)
        self.assertEqual(
            self.client.get("/api/v1/missing", headers=self.headers).status_code, 404
        )

    def test_workspace_identity_is_stable_and_not_a_path_or_key(self):
        first = self.client.post("/session/renew", headers=self.headers, json={}).json()
        second = self.client.post(
            "/session/exchange",
            headers={"Origin": self.origin},
            json={"nonce": self.sessions.bootstrap()},
        ).json()
        self.assertIn("workspace", first)
        self.assertEqual(first["workspace"], second["workspace"])
        self.assertEqual(len(first["workspace"]), 64)

    def test_json_validation_limits_and_no_unknown_command_side_effects(self):
        for content in ("{", "[]", '{"command":"SaveTarget", "input":NaN}', "{}"):
            response = self.client.post(
                "/api/v1/commands",
                headers={**self.headers, "Content-Type": "application/json"},
                content=content,
            )
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            self.client.post(
                "/api/v1/commands", headers=self.headers, content="data"
            ).status_code,
            415,
        )
        oversized = self.client.post(
            "/api/v1/commands",
            headers={**self.headers, "Content-Type": "application/json"},
            content='"' + "x" * (1024 * 1024) + '"',
        )
        self.assertEqual(oversized.status_code, 413)
        unknown = self.command("SubmitApplication", {"secret": "private resume text"})
        self.assertEqual(unknown.status_code, 400)
        self.assertNotIn("private resume text", unknown.text)

    def test_interview_commands_and_query_are_available_over_authenticated_http(self):
        job = self.command(
            "ImportJob",
            {"text_fields": {"title": "开发", "company": "HTTP测试"}},
        ).json()["data"]
        opportunity = self.command("SaveOpportunity", {"job_id": job["id"]}).json()["data"]
        scheduled = self.command(
            "SaveInterview",
            {
                "opportunity_id": opportunity["id"],
                "label": "一面",
                "starts_at": "2026-11-20T10:00:00+08:00",
                "ends_at": "2026-11-20T11:00:00+08:00",
                "time_zone": "Asia/Shanghai",
                "format": "online",
                "status": "planned",
                "reminder_offsets": [60],
            },
        )
        self.assertEqual(scheduled.status_code, 200, scheduled.text)
        identifier = scheduled.json()["data"]["id"]
        page = self.client.get("/api/v1/interviews?status=planned", headers=self.headers)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["items"][0]["schedule"]["id"], identifier)
        unknown_filter = self.client.get(
            "/api/v1/interviews?unexpected=yes", headers=self.headers
        )
        self.assertEqual(unknown_filter.status_code, 422, unknown_filter.text)

    def test_audio_attach_command_is_registered_at_http_boundary(self):
        unavailable = self.command(
            "AttachAudioImport",
            {"interview_id": str(uuid.uuid4()), "asset_id": str(uuid.uuid4())},
        )
        self.assertEqual(unavailable.status_code, 404, unavailable.text)

    def test_complete_http_flow_restart_receipt_conflict_and_two_step_confirmation(
        self,
    ):
        target = self.command(
            "SaveTarget",
            {"label": "后端", "criteria": {"keywords": ["Python"], "any_city": True}},
        )
        self.assertEqual(target.status_code, 200)
        resume = self.command(
            "ImportMaterial", {"label": "简历", "text": "本人核对的经历"}
        ).json()["data"]
        request = str(uuid.uuid4())
        fields = {
            "text_fields": {
                "title": "后端工程师",
                "company": "测试公司",
                "responsibilities": "开发",
                "requirements": "Python",
            }
        }
        response = self.command("ImportJob", fields, request=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(), self.command("ImportJob", fields, request=request).json()
        )
        self.assertEqual(
            self.command(
                "ImportJob",
                {"text_fields": {"title": "different", "company": "test"}},
                request=request,
            ).status_code,
            409,
        )
        job = response.json()["data"]
        opp = self.command("SaveOpportunity", {"job_id": job["id"]}).json()["data"]
        self.command(
            "RecordCooldown",
            {
                "opportunity_id": opp["id"],
                "scope": "job",
                "status": "present",
                "explanation": "招聘方说明",
                "evidence": {"items": [{"kind": "user", "text": "需冷却期"}]},
            },
            opp["revision"],
        )
        prep = self.command(
            "SavePreparation",
            {
                "opportunity_id": opp["id"],
                "job_version_id": job["current_version"]["id"],
                "resume_version_id": resume["id"],
                "channel": "官网",
            },
        ).json()["data"]
        first = self.command(
            "ConfirmPreparation",
            {"preparation_id": prep["id"], "step": "materials"},
            prep["revision"],
        ).json()["data"]
        self.assertEqual(first["next_step"], "cooldown")
        stale = self.command(
            "ConfirmPreparation",
            {"preparation_id": prep["id"], "step": "cooldown"},
            prep["revision"],
        )
        self.assertEqual(stale.status_code, 409)
        ready = self.command(
            "ConfirmPreparation",
            {"preparation_id": prep["id"], "step": "cooldown"},
            first["revision"],
        ).json()["data"]
        self.assertEqual(ready["next_step"], "manual_apply")
        url = "/api/v1/opportunities/" + opp["id"]
        self.assertEqual(
            self.client.get(url, headers=self.headers).json()["applications"], []
        )
        recorded = self.command(
            "RecordApplication",
            {
                "opportunity_id": opp["id"],
                "preparation_id": prep["id"],
                "job_version_id": job["current_version"]["id"],
                "resume_version_id": resume["id"],
                "channel": "官网",
                "outcome": "submitted",
                "submitted_at": "2026-11-05T00:00:00Z",
                "evidence": {"kind": "user_attestation", "statement": "看到成功页"},
            },
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertEqual(
            len(self.client.get(url, headers=self.headers).json()["applications"]), 1
        )
