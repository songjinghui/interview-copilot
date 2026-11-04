"""Explicit, non-destructive migration into a new, independently usable bundle."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path

from .database import Database, SchemaError, json_text, utc_now, utc_time
from ..jobs.store import SqliteJobStore, content_hash, decode_record

LEGACY_COLUMNS = {
    "jobs": [
        "source_key",
        "source_job_id",
        "content_hash",
        "payload",
        "first_fetched_at",
        "last_fetched_at",
    ],
    "job_versions": [
        "id",
        "source_key",
        "source_job_id",
        "content_hash",
        "payload",
        "fetched_at",
    ],
}


def validate_legacy(connection):
    objects = connection.execute(
        "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if {(row[0], row[1]) for row in objects} != {
        ("table", "jobs"),
        ("table", "job_versions"),
    }:
        raise SchemaError("Not the known two-table legacy schema")
    for table, expected in LEGACY_COLUMNS.items():
        if [
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        ] != expected:
            raise SchemaError("Unsupported legacy table shape")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SchemaError("Legacy database integrity check failed")


def _record(row, *, current=False):
    try:
        record = decode_record(json.loads(row["payload"]))
        if (record.source_key, record.source_job_id) != (
            row["source_key"],
            row["source_job_id"],
        ):
            raise ValueError("Record identity disagrees with row")
        # The spike did not update payload timestamps for unchanged content.
        timestamp = row["last_fetched_at"] if current else row["fetched_at"]
        utc_time(timestamp)
        return replace(record, fetched_at=timestamp)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise SchemaError("Invalid legacy record; source left unchanged") from error


def migrate_legacy(source: str | Path, output_directory: str | Path) -> dict:
    source = Path(source).resolve(strict=True)
    output = Path(output_directory).absolute()
    if output.exists():
        raise FileExistsError(output)
    if not source.is_file():
        raise SchemaError("Legacy source must be a regular SQLite file")
    output.parent.mkdir(parents=True, exist_ok=True)
    output = output.parent.resolve() / output.name
    if source == output or output in source.parents:
        raise SchemaError("Output must be separate from the source")
    # Staging is always a newly-created child of the checked output parent.
    with tempfile.TemporaryDirectory(
        prefix=".interview-migration-", dir=output.parent
    ) as temporary:
        staging = Path(temporary).resolve()
        if staging.parent != output.parent:
            raise SchemaError("Invalid staging location")
        source_connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        backup_connection = sqlite3.connect(staging / "legacy-backup.sqlite")
        try:
            source_connection.backup(backup_connection)
        finally:
            backup_connection.close()
            source_connection.close()
        snapshot = sqlite3.connect(staging / "legacy-backup.sqlite")
        snapshot.row_factory = sqlite3.Row
        report = {
            "schema_version": 1,
            "created_at": utc_now(),
            "source": str(source),
            "legacy_version_map": {},
            "job_map": {},
            "warnings": [],
        }
        try:
            validate_legacy(snapshot)
            current_rows = snapshot.execute(
                "SELECT * FROM jobs ORDER BY source_key,source_job_id"
            ).fetchall()
            history_rows = snapshot.execute(
                "SELECT * FROM job_versions ORDER BY id"
            ).fetchall()
            identities = {(r["source_key"], r["source_job_id"]) for r in current_rows}
            if any(
                (r["source_key"], r["source_job_id"]) not in identities
                for r in history_rows
            ):
                raise SchemaError("Legacy history contains an orphan job")
            with Database(staging / "app.sqlite") as database:
                store = SqliteJobStore(database)
                with database.transaction():
                    for row in history_rows:
                        result = store.write_observation(
                            _record(row),
                            provenance={
                                "kind": "legacy_import",
                                "legacy_version_id": row["id"],
                                "timestamp_uncertain": False,
                            },
                        )
                        report["legacy_version_map"][str(row["id"])] = result.version_id
                    for row in current_rows:
                        record = _record(row, current=True)
                        prior = store.get(record.source_key, record.source_job_id)
                        missing_transition = prior is None or content_hash(
                            prior
                        ) != content_hash(record)
                        result = store.write_observation(
                            record,
                            provenance={
                                "kind": "legacy_import",
                                "from_current_row": True,
                                "timestamp_uncertain": missing_transition,
                            },
                        )
                        database.connection.execute(
                            "UPDATE jobs SET first_observed_at=? WHERE id=?",
                            (utc_time(row["first_fetched_at"]), result.job_id),
                        )
                        report["job_map"][
                            json_text([record.source_key, record.source_job_id])
                        ] = result.job_id
                        if missing_transition:
                            report["warnings"].append(
                                {
                                    "job_id": result.job_id,
                                    "code": "LEGACY_HISTORY_GAP",
                                    "message": "Current content reconstructed from saved row; exact change time and other lost transitions cannot be recovered",
                                }
                            )
                if database.connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise SchemaError("Migrated references failed validation")
                if (
                    database.connection.execute("PRAGMA integrity_check").fetchone()[0]
                    != "ok"
                ):
                    raise SchemaError("Migrated database failed integrity check")
                database.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                report["jobs"] = len(current_rows)
                report["versions"] = database.connection.execute(
                    "SELECT count(*) FROM job_versions"
                ).fetchone()[0]
        finally:
            snapshot.close()
        report_path = staging / "migration-report.json"
        with report_path.open("w", encoding="utf-8") as stream:
            stream.write(json_text(report) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if output.exists():
            raise FileExistsError(output)
        # Windows rename refuses an existing destination. All readers are closed;
        # the new directory publishes database, backup and report together.
        os.rename(staging, output)
    return report
