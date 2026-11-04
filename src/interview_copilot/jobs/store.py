"""Job observations and immutable content revisions, backed by the v1 schema."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..storage import Database
from ..storage.database import digest, json_text, new_id, utc_time
from .model import JobRecord, JdCompleteness


@dataclass(frozen=True)
class UpsertResult:
    created: bool
    changed: bool
    job_id: str
    version_id: str
    observation_id: str

    @property
    def is_noop(self):
        """Content unchanged; a fresh observation is nevertheless persisted."""
        return not self.created and not self.changed


def content_hash(record: JobRecord) -> str:
    payload = asdict(record)
    for field in ("fetched_at", "fetch_method", "source_refreshed_at"):
        payload.pop(field, None)
    return digest(payload)


def decode_record(payload):
    data = dict(payload)
    data["locations"] = tuple(data.get("locations") or ())
    return JobRecord(**data)


class SqliteJobStore:
    def __init__(self, path: str | Path | Database = ":memory:"):
        self._owns_database = not isinstance(path, Database)
        self.database = Database(path) if self._owns_database else path
        self._conn = self.database.connection

    def close(self):
        if self._owns_database:
            self.database.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def upsert(
        self, record: JobRecord, *, provenance: dict | None = None
    ) -> UpsertResult:
        with self.database.transaction():
            return self.write_observation(record, provenance=provenance)

    def write_observation(self, record: JobRecord, *, provenance: dict | None = None):
        """Participate in an existing application transaction; no nested commit."""
        if not self._conn.in_transaction:
            raise RuntimeError("Observation writes require an application transaction")
        observed_at = utc_time(record.fetched_at)
        fingerprint = content_hash(record)
        self._conn.execute(
            "INSERT INTO sources(key,display_name,adapter_version,updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO NOTHING",
            (record.source_key, record.source_key, "record-import", observed_at),
        )
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE source_key=? AND external_key=?",
            (record.source_key, record.source_job_id),
        ).fetchone()
        created = row is None
        job_id = new_id() if created else row["id"]
        if created:
            self._conn.execute(
                "INSERT INTO jobs(id,source_key,external_key,first_observed_at,last_observed_at) VALUES(?,?,?,?,?)",
                (
                    job_id,
                    record.source_key,
                    record.source_job_id,
                    observed_at,
                    observed_at,
                ),
            )
        current = (
            None
            if created
            else self._conn.execute(
                "SELECT * FROM job_versions WHERE id=?", (row["current_version_id"],)
            ).fetchone()
        )
        changed = current is None or current["content_hash"] != fingerprint
        version_id = new_id() if changed else current["id"]
        complete = record.jd_completeness is JdCompleteness.COMPLETE
        if changed:
            revision = self._conn.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM job_versions WHERE job_id=?",
                (job_id,),
            ).fetchone()[0]
            completeness = (
                "complete"
                if complete
                else (
                    "partial"
                    if (record.responsibilities or record.requirements)
                    else "summary"
                )
            )
            self._conn.execute(
                "INSERT INTO job_versions(id,job_id,revision,title,company_name,original_url,locations_json,salary_text,experience_text,education_text,description_text,requirements_text,completeness,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    job_id,
                    revision,
                    record.title,
                    record.company or "未披露",
                    record.source_url,
                    json_text(record.locations),
                    record.salary_raw,
                    record.experience_raw,
                    record.education_raw,
                    record.responsibilities,
                    record.requirements,
                    completeness,
                    fingerprint,
                    observed_at,
                ),
            )
        observation_id = new_id()
        # Preserve raw unknown values and fields absent from display columns.
        payload = {
            "schema_version": 1,
            "record": asdict(record),
            "provenance": provenance or {"kind": "observation"},
        }
        self._conn.execute(
            "INSERT INTO job_observations(id,job_id,version_id,observed_at,method,observed_json) VALUES(?,?,?,?,?,?)",
            (
                observation_id,
                job_id,
                version_id,
                observed_at,
                "legacy_import" if provenance else record.fetch_method,
                json_text(payload),
            ),
        )
        last_complete = (
            version_id
            if complete
            else (None if created else row["last_complete_version_id"])
        )
        self._conn.execute(
            "UPDATE jobs SET current_version_id=?,last_complete_version_id=?,last_observed_at=? WHERE id=?",
            (version_id, last_complete, observed_at, job_id),
        )
        return UpsertResult(created, changed, job_id, version_id, observation_id)

    def _record_for_version(self, version_id, *, latest=False):
        row = self._conn.execute(
            "SELECT observed_json FROM job_observations WHERE version_id=? ORDER BY rowid "
            + ("DESC" if latest else "ASC")
            + " LIMIT 1",
            (version_id,),
        ).fetchone()
        return (
            None
            if row is None
            else decode_record(json.loads(row["observed_json"])["record"])
        )

    def get(self, source_key, source_job_id):
        row = self._conn.execute(
            "SELECT current_version_id FROM jobs WHERE source_key=? AND external_key=?",
            (source_key, source_job_id),
        ).fetchone()
        return None if row is None else self._record_for_version(row[0], latest=True)

    def list(self, source_key=None):
        sql = "SELECT current_version_id FROM jobs"
        parameters = ()
        if source_key is not None:
            sql += " WHERE source_key=?"
            parameters = (source_key,)
        sql += " ORDER BY last_observed_at DESC,id"
        return [
            self._record_for_version(row[0], latest=True)
            for row in self._conn.execute(sql, parameters)
        ]

    def versions(self, source_key, source_job_id):
        rows = self._conn.execute(
            "SELECT v.id FROM job_versions v JOIN jobs j ON j.id=v.job_id WHERE j.source_key=? AND j.external_key=? ORDER BY v.revision",
            (source_key, source_job_id),
        )
        return [self._record_for_version(row[0]) for row in rows]

    def details(self, source_key, source_job_id):
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE source_key=? AND external_key=?",
            (source_key, source_job_id),
        ).fetchone()
        if row is None:
            return None

        def view(version_id):
            if version_id is None:
                return None
            version = dict(
                self._conn.execute(
                    "SELECT * FROM job_versions WHERE id=?", (version_id,)
                ).fetchone()
            )
            observation = self._conn.execute(
                "SELECT * FROM job_observations WHERE version_id=? ORDER BY rowid DESC LIMIT 1",
                (version_id,),
            ).fetchone()
            version["record"] = asdict(
                self._record_for_version(version_id, latest=True)
            )
            version["observed_at"] = observation["observed_at"]
            version["provenance"] = json.loads(observation["observed_json"])[
                "provenance"
            ]
            return version

        return {
            "id": row["id"],
            "current_version": view(row["current_version_id"]),
            "last_complete_version": view(row["last_complete_version_id"]),
        }
