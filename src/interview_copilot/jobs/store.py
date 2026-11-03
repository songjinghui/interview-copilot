"""岗位记录的本地存储。

为什么用 SQLite：标准库自带、无需新增依赖；同一岗位重复获取必须幂等，
内容变化要留历史版本（VISION §4.2：岗位关闭或内容变化时保留历史版本）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from .model import JobRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    source_key       TEXT NOT NULL,
    source_job_id    TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    payload          TEXT NOT NULL,
    first_fetched_at TEXT NOT NULL,
    last_fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source_key, source_job_id)
);

CREATE TABLE IF NOT EXISTS job_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key    TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    payload       TEXT NOT NULL,
    fetched_at    TEXT NOT NULL,
    UNIQUE (source_key, source_job_id, content_hash)
);
"""


@dataclass(frozen=True)
class UpsertResult:
    """一次写入的结果，区分“新建”与“内容变化”，便于界面提示。"""

    created: bool
    changed: bool

    @property
    def is_noop(self) -> bool:
        return not self.created and not self.changed


def content_hash(record: JobRecord) -> str:
    """内容指纹：排除抓取时间，保证同一内容重复获取不产生新版本。"""
    payload = asdict(record)
    payload.pop("fetched_at", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SqliteJobStore:
    """岗位记录存储。传入 ':memory:' 可用于测试。"""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteJobStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert(self, record: JobRecord) -> UpsertResult:
        digest = content_hash(record)
        payload = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
        row = self._conn.execute(
            "SELECT content_hash, first_fetched_at FROM jobs"
            " WHERE source_key = ? AND source_job_id = ?",
            (record.source_key, record.source_job_id),
        ).fetchone()

        if row is None:
            self._conn.execute(
                "INSERT INTO jobs (source_key, source_job_id, content_hash, payload,"
                " first_fetched_at, last_fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.source_key,
                    record.source_job_id,
                    digest,
                    payload,
                    record.fetched_at,
                    record.fetched_at,
                ),
            )
            self._insert_version(record, digest, payload)
            self._conn.commit()
            return UpsertResult(created=True, changed=True)

        if row["content_hash"] == digest:
            self._conn.execute(
                "UPDATE jobs SET last_fetched_at = ?"
                " WHERE source_key = ? AND source_job_id = ?",
                (record.fetched_at, record.source_key, record.source_job_id),
            )
            self._conn.commit()
            return UpsertResult(created=False, changed=False)

        self._conn.execute(
            "UPDATE jobs SET content_hash = ?, payload = ?, last_fetched_at = ?"
            " WHERE source_key = ? AND source_job_id = ?",
            (digest, payload, record.fetched_at, record.source_key, record.source_job_id),
        )
        self._insert_version(record, digest, payload)
        self._conn.commit()
        return UpsertResult(created=False, changed=True)

    def _insert_version(self, record: JobRecord, digest: str, payload: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO job_versions"
            " (source_key, source_job_id, content_hash, payload, fetched_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (record.source_key, record.source_job_id, digest, payload, record.fetched_at),
        )

    def get(self, source_key: str, source_job_id: str) -> JobRecord | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE source_key = ? AND source_job_id = ?",
            (source_key, source_job_id),
        ).fetchone()
        return None if row is None else _decode(row["payload"])

    def list(self, source_key: str | None = None) -> list[JobRecord]:
        if source_key is None:
            rows = self._conn.execute(
                "SELECT payload FROM jobs ORDER BY last_fetched_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT payload FROM jobs WHERE source_key = ?"
                " ORDER BY last_fetched_at DESC",
                (source_key,),
            ).fetchall()
        return [_decode(row["payload"]) for row in rows]

    def versions(self, source_key: str, source_job_id: str) -> list[JobRecord]:
        rows = self._conn.execute(
            "SELECT payload FROM job_versions"
            " WHERE source_key = ? AND source_job_id = ? ORDER BY id",
            (source_key, source_job_id),
        ).fetchall()
        return [_decode(row["payload"]) for row in rows]


def _decode(payload: str) -> JobRecord:
    data = json.loads(payload)
    data["locations"] = tuple(data.get("locations") or ())
    return JobRecord(**data)
