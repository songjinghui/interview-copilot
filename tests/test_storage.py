"""Integration contracts for isolated v1 storage and legacy migration."""

import hashlib
import importlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from tests.test_job_store import make_record


def feature(test, module):
    test.assertIsNotNone(
        importlib.util.find_spec(module), f"Required storage feature missing: {module}"
    )
    return importlib.import_module(module)


LEGACY_SQL = """
CREATE TABLE jobs(source_key TEXT NOT NULL,source_job_id TEXT NOT NULL,content_hash TEXT NOT NULL,
 payload TEXT NOT NULL,first_fetched_at TEXT NOT NULL,last_fetched_at TEXT NOT NULL,
 PRIMARY KEY(source_key,source_job_id));
CREATE TABLE job_versions(id INTEGER PRIMARY KEY AUTOINCREMENT,source_key TEXT NOT NULL,
 source_job_id TEXT NOT NULL,content_hash TEXT NOT NULL,payload TEXT NOT NULL,fetched_at TEXT NOT NULL,
 UNIQUE(source_key,source_job_id,content_hash));
"""


def legacy(path):
    db = sqlite3.connect(path)
    db.executescript(LEGACY_SQL)
    records = [
        make_record(requirements=t, fetched_at=f"2026-11-{day:02}T12:00:00+08:00")
        for day, t in [(3, "A"), (4, "B"), (5, "A")]
    ]
    for record in records[:2]:
        db.execute(
            "INSERT INTO job_versions(source_key,source_job_id,content_hash,payload,fetched_at) VALUES(?,?,?,?,?)",
            (
                record.source_key,
                record.source_job_id,
                record.requirements,
                json.dumps(asdict(record)),
                record.fetched_at,
            ),
        )
    current = records[-1]
    db.execute(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?)",
        (
            current.source_key,
            current.source_job_id,
            "A",
            json.dumps(asdict(current)),
            records[0].fetched_at,
            current.fetched_at,
        ),
    )
    db.commit()
    db.close()


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.storage = feature(self, "interview_copilot.storage")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "isolated.sqlite"

    def test_initial_schema_is_packaged_and_matches_approved_relations(self):
        with self.storage.Database(self.path) as db:
            self.assertEqual(
                db.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
            )
            self.assertEqual(
                db.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal"
            )
            self.assertEqual(
                db.connection.execute("PRAGMA synchronous").fetchone()[0], 2
            )
            self.assertEqual(
                db.connection.execute(
                    "SELECT count(*) FROM schema_migrations"
                ).fetchone()[0],
                1,
            )
            expected = sqlite3.connect(":memory:")
            self.addCleanup(expected.close)
            expected.executescript(
                (Path(__file__).resolve().parents[1] / "docs/schema.sql").read_text(
                    encoding="utf-8"
                )
            )
            query = "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
            self.assertEqual(
                [tuple(r) for r in db.connection.execute(query)],
                expected.execute(query).fetchall(),
            )

    def test_reopen_does_not_reapply_initial_migration(self):
        with self.storage.Database(self.path) as db:
            checksum = db.connection.execute(
                "SELECT checksum FROM schema_migrations"
            ).fetchone()[0]
        with self.storage.Database(self.path) as db:
            self.assertEqual(
                db.connection.execute(
                    "SELECT checksum FROM schema_migrations"
                ).fetchone()[0],
                checksum,
            )

    def test_unknown_schema_and_legacy_are_refused_without_modification(self):
        for kind in ("unknown", "legacy"):
            path = Path(self.temp.name) / f"{kind}.sqlite"
            if kind == "legacy":
                legacy(path)
            else:
                with sqlite3.connect(path) as raw:
                    raw.execute("CREATE TABLE personal_data(value TEXT)")
                raw.close()
            before = path.read_bytes()
            with self.assertRaises(self.storage.SchemaError):
                self.storage.Database(path)
            self.assertEqual(path.read_bytes(), before)

    def test_migration_checksum_tampering_refused(self):
        with self.storage.Database(self.path) as db:
            with db.transaction():
                db.connection.execute(
                    "UPDATE schema_migrations SET checksum='tampered'"
                )
        with self.assertRaises(self.storage.SchemaError):
            self.storage.Database(self.path)

    def test_transaction_rolls_back_all_changes_on_error(self):
        with self.storage.Database(self.path) as db:
            with self.assertRaises(RuntimeError):
                with db.transaction():
                    db.connection.execute(
                        "INSERT INTO settings VALUES('x','{}',1,'2026-11-04T00:00:00.000Z')"
                    )
                    raise RuntimeError("injected interruption")
            self.assertEqual(
                db.connection.execute("SELECT count(*) FROM settings").fetchone()[0], 0
            )


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.storage = feature(self, "interview_copilot.storage")
        self.migration = feature(self, "interview_copilot.storage.legacy")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "old.sqlite"
        legacy(self.source)
        self.destination = Path(self.temp.name) / "new-bundle"

    def test_copy_migration_preserves_source_backup_and_known_history(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        report = self.migration.migrate_legacy(self.source, self.destination)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
        self.assertTrue((self.destination / "legacy-backup.sqlite").is_file())
        self.assertTrue((self.destination / "migration-report.json").is_file())
        from interview_copilot.jobs.store import SqliteJobStore

        with SqliteJobStore(self.destination / "app.sqlite") as jobs:
            self.assertEqual(
                [r.requirements for r in jobs.versions("meituan", "4697320043")],
                ["A", "B", "A"],
            )
            details = jobs.details("meituan", "4697320043")
            self.assertEqual(details["current_version"]["revision"], 3)
        self.assertEqual(len(report["legacy_version_map"]), 2)
        self.assertTrue(report["warnings"])

    def test_existing_destination_not_overwritten(self):
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.migration.migrate_legacy(self.source, self.destination)
        self.assertEqual(marker.read_text(), "keep")

    def test_corrupt_payload_fails_without_publishing_new_bundle(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE jobs SET payload='not-json'")
        db.close()
        before = self.source.read_bytes()
        with self.assertRaises(self.storage.SchemaError):
            self.migration.migrate_legacy(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), before)

    def test_publish_failure_keeps_original_and_no_partial_destination(self):
        before = self.source.read_bytes()
        with patch.object(
            self.migration.os,
            "rename",
            side_effect=OSError("injected publication failure"),
        ):
            with self.assertRaises(OSError):
                self.migration.migrate_legacy(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), before)

    def test_committed_wal_content_is_in_snapshot_even_without_checkpoint(self):
        from interview_copilot.jobs.store import SqliteJobStore

        with sqlite3.connect(self.source) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            payload = json.loads(
                writer.execute("SELECT payload FROM jobs").fetchone()[0]
            )
            payload["requirements"] = "Committed in WAL"
            writer.execute("UPDATE jobs SET payload=?", (json.dumps(payload),))
        try:
            self.assertTrue(Path(str(self.source) + "-wal").is_file())
            self.migration.migrate_legacy(self.source, self.destination)
            with SqliteJobStore(self.destination / "app.sqlite") as jobs:
                self.assertEqual(
                    jobs.get("meituan", "4697320043").requirements, "Committed in WAL"
                )
            self.assertEqual(
                json.loads(writer.execute("SELECT payload FROM jobs").fetchone()[0])[
                    "requirements"
                ],
                "Committed in WAL",
            )
        finally:
            writer.close()

    def test_unknown_schema_is_not_accepted_as_legacy(self):
        with sqlite3.connect(self.source) as db:
            db.execute("CREATE TABLE unrelated(secret TEXT)")
        db.close()
        before = self.source.read_bytes()
        with self.assertRaises(self.storage.SchemaError):
            self.migration.migrate_legacy(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
