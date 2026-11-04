from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from uuid import uuid4


class SchemaError(ValueError):
    """The supplied database is not a supported application schema."""


def new_id() -> str:
    return str(uuid4())


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def utc_time(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include an explicit timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def initial_schema() -> str:
    return (
        files("interview_copilot.storage")
        .joinpath("migrations/001_initial.sql")
        .read_text(encoding="utf-8")
    )


def schema_signature(connection):
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


@lru_cache(maxsize=1)
def approved_signature():
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(initial_schema())
        return schema_signature(connection)
    finally:
        connection.close()


def statements(script):
    """Split our packaged SQL without executescript's implicit COMMIT."""
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ""
    if any(
        line.strip() and not line.lstrip().startswith("--")
        for line in pending.splitlines()
    ):
        raise SchemaError("Incomplete packaged migration")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._closed = False
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA busy_timeout=5000")
            checksum = hashlib.sha256(initial_schema().encode("utf-8")).hexdigest()
            with self.transaction():
                objects = schema_signature(self.connection)
                if not objects:
                    for statement in statements(initial_schema()):
                        self.connection.execute(statement)
                    self.connection.execute(
                        "INSERT INTO schema_migrations VALUES(1,?,?)",
                        (checksum, utc_now()),
                    )
                    self.connection.execute("PRAGMA user_version=1")
                else:
                    if objects != approved_signature():
                        raise SchemaError(
                            "Unknown or legacy schema; use explicit isolated legacy migration"
                        )
                    rows = self.connection.execute(
                        "SELECT version,checksum FROM schema_migrations ORDER BY version"
                    ).fetchall()
                    if [tuple(r) for r in rows] != [(1, checksum)]:
                        raise SchemaError("Unsupported migration version or checksum")
                    if (
                        self.connection.execute("PRAGMA user_version").fetchone()[0]
                        != 1
                    ):
                        raise SchemaError("Unsupported schema version")
            if self.path != ":memory:":
                self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise RuntimeError(
                "Nested transactions are not supported; use one application transaction"
            )
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
