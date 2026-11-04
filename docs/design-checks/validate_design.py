"""Executable checks for the SQL DESIGN; never opens an application database.

Run: python -X utf8 docs/design-checks/validate_design.py
These tests do not certify UI, workers, platform integrations or migrations.
"""
from pathlib import Path
import sqlite3
import sys
import unittest

SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"
NOW = "2026-11-04T08:30:00.000Z"


class DesignChecks(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.add("sources", key="manual", display_name="Manual", adapter_version="1", updated_at=NOW)
        self.add("opportunities", id="o", title="Role", company_name="Example", created_at=NOW, updated_at=NOW)
        self.interview("i")

    def tearDown(self):
        self.db.close()

    def add(self, table, **fields):
        # Identifiers are fixed by this test file; all data remains parameterized.
        self.db.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", tuple(fields.values()))

    def columns(self, table):
        return {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}

    def interview(self, id, **fields):
        self.add("interviews", id=id, opportunity_id="o", label="Round", time_zone="Asia/Shanghai", format="online", created_at=NOW, updated_at=NOW, **fields)

    def audio(self, id):
        self.add("audio_assets", id=id, interview_id="i", revision=1, origin="import", status="finalized", completeness="complete", created_at=NOW, finalized_at=NOW)

    def task(self, id):
        self.add("background_tasks", id=id, kind="transcribe", dedup_key=id, input_json='{}', created_at=NOW, updated_at=NOW)

    def version(self, id, revision, digest="A"):
        self.add("job_versions", id=id, job_id="j", revision=revision, title="Role", company_name="Example", completeness="summary", content_hash=digest, created_at=NOW)

    def job(self):
        self.add("jobs", id="j", source_key="manual", external_key="job", first_observed_at=NOW, last_observed_at=NOW)
        self.version("j1", 1)

    def test_schema_integrity(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_A_B_A_three_revisions_and_immutable_history(self):
        self.job()
        self.version("j2", 2, "B")
        self.version("j3", 3, "A")
        self.assertEqual(self.db.execute("SELECT content_hash FROM job_versions ORDER BY revision").fetchall(), [("A",),("B",),("A",)])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE job_versions SET title='changed' WHERE id='j1'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.version("duplicate", 3)

    def test_R1_account_scoped_feedback_and_invitation(self):
        self.assertIn("account_id", self.columns("feedback_items"), "R1: feedback must persist stable account identity")
        self.assertIn("source_account_id", self.columns("interviews"), "R1: invitation identity cannot depend on a message ID")
        for a in ("a", "b"):
            self.add("source_accounts", id=a, source_key="manual", account_key=a, display_name=a, updated_at=NOW)
            self.add("feedback_items", id="f-"+a, source_key="manual", account_id=a, external_key="42", text_content=a, received_at=NOW)
            self.interview("invite-"+a, source_account_id=a, source_event_key="meeting", source_feedback_id="f-"+a)
        self.assertEqual(self.db.execute("SELECT count(*) FROM feedback_items").fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.add("feedback_items", id="duplicate", source_key="manual", account_id="a", external_key="42", text_content="same", received_at=NOW)
        self.add("feedback_items", id="reschedule", source_key="manual", account_id="a", external_key="43", text_content="new time", received_at=NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.interview("duplicate-invite", source_account_id="a", source_event_key="meeting", source_feedback_id="reschedule")
        self.db.execute("UPDATE interviews SET starts_at=?,source_feedback_id='reschedule' WHERE source_account_id='a' AND source_event_key='meeting'", (NOW,))
        self.add("feedback_items", id="cancel", source_key="manual", account_id="a", external_key="44", text_content="cancelled", received_at=NOW)
        self.db.execute("UPDATE interviews SET status='cancelled',source_feedback_id='cancel' WHERE source_account_id='a' AND source_event_key='meeting'")
        self.assertEqual(self.db.execute("SELECT count(*) FROM interviews WHERE source_account_id='a'").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT status FROM interviews WHERE source_account_id='b'").fetchone()[0], "planned")

    def test_R2_combined_transcript_audio_provenance_survives_reload(self):
        self.assertTrue({"interview_id", "audio_asset_id", "source_version_id", "source_segment_key"} <= self.columns("transcript_segments"), "R2: each combined segment needs durable audio and source provenance")
        for n, a in enumerate(("a", "b"), 1):
            self.audio(a)
            self.add("transcript_versions", id="t-"+a, interview_id="i", revision=n, audio_asset_id=a, origin="asr", content_hash=a, created_at=NOW)
            self.add("transcript_segments", version_id="t-"+a, interview_id="i", segment_key="s", ordinal=0, speaker="unknown", text_content=a, audio_asset_id=a, start_ms=30000, end_ms=40000)
        self.add("transcript_versions", id="combined", interview_id="i", revision=3, origin="combined", content_hash="c", created_at=NOW)
        self.add("transcript_versions", id="corrected", interview_id="i", revision=4, parent_version_id="combined", origin="correction", content_hash="d", created_at=NOW)
        for ver in ("combined", "corrected"):
            for n,a in enumerate(("a", "b")):
                self.add("transcript_segments", version_id=ver, interview_id="i", segment_key=a, ordinal=n, speaker="candidate", text_content=a, audio_asset_id=a, source_version_id="t-"+a, source_segment_key="s", start_ms=30000, end_ms=40000)
        self.db.commit()
        restored = sqlite3.connect(":memory:")
        try:
            self.db.backup(restored)
            expected = [("a",30000,40000),("b",30000,40000)]
            for ver in ("combined", "corrected"):
                self.assertEqual(restored.execute("SELECT audio_asset_id,start_ms,end_ms FROM transcript_segments WHERE version_id=? ORDER BY ordinal", (ver,)).fetchall(), expected)
        finally:
            restored.close()

    def test_R3_request_generation_separates_rerun_from_recovery(self):
        self.assertIn("request_generation", self.columns("transcription_jobs"), "R3: explicit same-config rerun requires a separate request generation")
        self.audio("a")
        for generation in (1,2):
            self.task(str(generation))
            self.add("transcription_jobs", task_id=str(generation), audio_asset_id="a", asset_revision=1, config_hash="same", config_json="{}", request_generation=generation)
        self.task("duplicate")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add("transcription_jobs", task_id="duplicate", audio_asset_id="a", asset_revision=1, config_hash="same", config_json="{}", request_generation=2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM transcription_jobs").fetchone()[0], 2)

    def test_R4_resume_exception_is_recoverable_and_required_to_confirm(self):
        self.assertIn("resume_exception", self.columns("application_preparations"), "R4: missing-resume explanation is business data")
        self.job()
        self.add("application_preparations", id="p", opportunity_id="o", job_version_id="j1", channel="manual", cooldown_snapshot_json="{}", cooldown_status="unknown", created_at=NOW, updated_at=NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE application_preparations SET material_confirmed_at=?,status='ready_for_manual_apply' WHERE id='p'", (NOW,))
        self.db.execute("UPDATE application_preparations SET resume_exception='Channel does not require a resume',material_confirmed_at=?,status='ready_for_manual_apply' WHERE id='p'", (NOW,))
        self.db.commit()
        self.assertEqual(self.db.execute("SELECT resume_exception FROM application_preparations WHERE id='p'").fetchone()[0], "Channel does not require a resume")

    def test_present_requires_two_confirmations(self):
        self.job()
        fields = {"resume_exception":"No resume required"} if "resume_exception" in self.columns("application_preparations") else {}
        self.add("application_preparations", id="p", opportunity_id="o", job_version_id="j1", channel="manual", cooldown_snapshot_json="{}", cooldown_status="present", created_at=NOW, updated_at=NOW, **fields)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE application_preparations SET material_confirmed_at=?,status='ready_for_manual_apply' WHERE id='p'", (NOW,))
        self.db.execute("UPDATE application_preparations SET material_confirmed_at=?,cooldown_confirmed_at=?,status='ready_for_manual_apply' WHERE id='p'", (NOW,NOW))
        self.assertEqual(self.db.execute("SELECT count(*) FROM applications").fetchone()[0], 0)

    def test_cross_interview_review_reference_rejected(self):
        self.interview("other")
        self.task("review-task")
        self.add("interview_context_versions", id="ctx", interview_id="i", revision=1, job_title="Role", created_at=NOW)
        self.add("transcript_versions", id="txt", interview_id="other", revision=1, origin="manual", content_hash="x", created_at=NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.add("review_runs", id="run", task_id="review-task", interview_id="i", context_version_id="ctx", transcript_version_id="txt", model_config_json="{}", prompt_revision="1", created_at=NOW)

    def test_done_improvement_requires_completion_time(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.add("improvement_items", id="bad", title="Improve", action="Practice", status="done", created_at=NOW, updated_at=NOW)
        self.add("improvement_items", id="good", title="Improve", action="Practice", status="done", completed_at=NOW, created_at=NOW, updated_at=NOW)
        self.assertEqual(self.db.execute("SELECT status FROM improvement_items WHERE id='good'").fetchone()[0], "done")

    def test_task_dedup_and_running_owner_constraints(self):
        self.task("one")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add("background_tasks", id="two", kind="transcribe", dedup_key="one", input_json="{}", created_at=NOW, updated_at=NOW)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE background_tasks SET status='running' WHERE id='one'")


def write_reference():
    """Derive the review dictionary from the SQL; no second field definition."""
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    out = ["# 数据字段字典（由 SQL 派生）", "",
           "生成源：[schema.sql](schema.sql)。业务语义、JSON 形状与事务见[数据库设计](database-design.md)。",
           "", "重新生成：`python -X utf8 docs/design-checks/validate_design.py --write-reference`。",
           "程序先运行设计检查，仅成功时更新本文。NOT NULL / 默认值按 SQLite 实际 schema 读取；联合唯一、CHECK 与触发器以 SQL 为准。", ""]
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        out += [f"## {table}", "", "| 字段 | 类型 | 必填 | 默认 | 主键次序 |", "|---|---|---|---|---|"]
        for _, name, kind, required, default, pk in db.execute(f"PRAGMA table_info({table})"):
            out.append(f"| `{name}` | {kind} | {'是' if required or pk else '否'} | `{default}` | {pk or '—'} |")
        out += ["", "外键（同一编号为复合外键）：", ""]
        fks = db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        out.extend([f"- {r[0]}.{r[1]} `{r[3]}` → `{r[2]}.{r[4]}`；ON DELETE {r[6]}" for r in fks] or ["无。"])
        out += ["", "索引：", ""]
        indexes = db.execute(f"PRAGMA index_list({table})").fetchall()
        for idx in indexes:
            fields = ", ".join(r[2] for r in db.execute(f"PRAGMA index_info('{idx[1]}')"))
            out.append(f"- `{idx[1]}`：({fields}){'；唯一' if idx[2] else ''}")
        if not indexes:
            out.append("主键 rowid 定位，无附加索引。")
        out.append("")
    db.close()
    SCHEMA.with_name("schema-reference.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    generate = "--write-reference" in sys.argv
    if generate:
        sys.argv.remove("--write-reference")
    result = unittest.main(verbosity=2, exit=False).result
    if result.wasSuccessful() and generate:
        write_reference()
    sys.exit(0 if result.wasSuccessful() else 1)
