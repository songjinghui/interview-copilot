"""Local workbench commands and durable public read views."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import wave
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones
from .application import (
    ApplicationService,
    ApplicationError,
    choice,
    public_url,
    structured,
    text,
)
from .jobs.model import JobRecord
from .jobs.store import SqliteJobStore
from .storage.database import new_id, utc_now, utc_time, digest, json_text


def decoded(row):
    result = dict(row)
    if "active" in result:
        result["active"] = bool(result["active"])
    for key in list(result):
        if key.endswith("_json"):
            result[key[:-5]] = json.loads(result.pop(key))
    return result


class WorkbenchService(ApplicationService):
    def __init__(self, database):
        super().__init__(database)
        self.jobs = SqliteJobStore(database)
        self.commands["ImportJob"] = (self._import_job, "url text_fields")
        self.commands["SaveInterview"] = (
            self._save_interview,
            "id opportunity_id application_id label starts_at ends_at time_zone format location status reminder_offsets",
        )
        self.commands["AcknowledgeReminder"] = (
            self._acknowledge_reminder,
            "reminder_id",
        )
        self.commands["AttachAudioImport"] = (
            self._attach_audio_import,
            "interview_id asset_id",
        )

    @staticmethod
    def _interview_time(value, field):
        if value is None:
            return None
        try:
            return utc_time(value)
        except (TypeError, ValueError, OverflowError):
            raise ApplicationError(
                "VALIDATION", f"{field} must be an ISO timestamp with timezone"
            ) from None

    @staticmethod
    def _interview_zone(value):
        value = text(value, "time_zone")
        if not re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*", value):
            raise ApplicationError("VALIDATION", "time_zone must be an IANA zone name")
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError:
            if not available_timezones():
                raise ApplicationError(
                    "TIMEZONE_DATA_UNAVAILABLE",
                    "IANA time-zone data is required to validate this schedule",
                    retryable=True,
                ) from None
            raise ApplicationError("VALIDATION", "Unknown IANA time_zone") from None

    def _reminder_offsets(self, value, *, has_start):
        if value is None:
            value = []
        if not isinstance(value, list) or any(
            type(offset) is not int or not 1 <= offset <= 43200 for offset in value
        ):
            raise ApplicationError(
                "VALIDATION", "reminder_offsets must be unique positive minutes up to 30 days"
            )
        if len(set(value)) != len(value):
            raise ApplicationError("VALIDATION", "reminder_offsets must be unique")
        if value and not has_start:
            raise ApplicationError(
                "VALIDATION", "Scheduled reminders require a known interview start"
            )
        return sorted(value, reverse=True)

    def _save_interview(self, p, expected):
        required = {"opportunity_id", "label", "time_zone"}
        if required - set(p):
            raise ApplicationError("VALIDATION", "Missing required interview fields")
        opportunity = self._row("opportunities", p["opportunity_id"])
        application_id = p.get("application_id")
        if application_id is not None:
            application = self._row("applications", application_id)
            if application["opportunity_id"] != opportunity["id"]:
                raise ApplicationError(
                    "VALIDATION", "Application belongs to another opportunity"
                )
        label = text(p.get("label"), "label")
        zone_name = text(p.get("time_zone"), "time_zone")
        self._interview_zone(zone_name)
        starts_at = self._interview_time(p.get("starts_at"), "starts_at")
        ends_at = self._interview_time(p.get("ends_at"), "ends_at")
        if ends_at and (not starts_at or ends_at <= starts_at):
            raise ApplicationError(
                "VALIDATION", "ends_at must be later than a known starts_at"
            )
        offsets = self._reminder_offsets(
            p.get("reminder_offsets", []), has_start=starts_at is not None
        )
        # Instants are canonical UTC values; time_zone is display metadata.
        # Do not require the input's representation offset to match that zone:
        # UTC and local-offset strings can denote the same instant.
        fields = {
            "opportunity_id": opportunity["id"],
            "application_id": application_id,
            "label": label,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "time_zone": zone_name,
            "format": choice(
                p.get("format", "unknown"),
                {"online", "onsite", "phone", "unknown"},
                "format",
            ),
            "location": text(p["location"], "location") if p.get("location") else None,
            "status": choice(
                p.get("status", "planned"),
                {"planned", "completed", "cancelled"},
                "status",
            ),
        }
        if fields["status"] == "planned" and starts_at is None:
            raise ApplicationError(
                "VALIDATION", "A planned interview requires a start time"
            )
        if p.get("id"):
            row = self._expected("interviews", p["id"], expected)
            if row["opportunity_id"] != opportunity["id"]:
                raise ApplicationError("VALIDATION", "Cannot move an interview")
            self.connection.execute(
                "UPDATE interviews SET opportunity_id=?,application_id=?,label=?,starts_at=?,ends_at=?,time_zone=?,format=?,location=?,status=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?",
                (
                    fields["opportunity_id"], fields["application_id"], fields["label"],
                    fields["starts_at"], fields["ends_at"], fields["time_zone"],
                    fields["format"], fields["location"], fields["status"],
                    utc_now(), row["id"], expected,
                ),
            )
            identifier = row["id"]
            # Keep already delivered/read reminders as history; replace only plans
            # that have not fired yet, atomically with the schedule revision.
            self.connection.execute(
                "UPDATE reminders SET status='cancelled' WHERE interview_id=? AND status='pending'",
                (identifier,),
            )
        else:
            if expected is not None:
                raise ApplicationError(
                    "VALIDATION", "expected_revision is only valid when editing an interview"
                )
            identifier, now = new_id(), utc_now()
            self._insert(
                "interviews", id=identifier, **fields, created_at=now, updated_at=now
            )
        reminder_ids = []
        if starts_at and fields["status"] == "planned":
            start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
            now = datetime.fromisoformat(utc_now().replace("Z", "+00:00"))
            for offset in offsets:
                reminder_id = new_id()
                due = start - timedelta(minutes=offset)
                scheduled = utc_time(due.isoformat(timespec="milliseconds"))
                self._insert(
                    "reminders",
                    id=reminder_id,
                    interview_id=identifier,
                    cooldown_note_id=None,
                    scheduled_for=scheduled,
                    # The delivery worker is not part of this slice. Do not
                    # leave an already-expired reminder looking deliverable.
                    status="missed" if due <= now else "pending",
                    delivered_at=None,
                    created_at=utc_now(),
                )
                reminder_ids.append(reminder_id)
        result = self.interview_detail(identifier)
        return {
            **result["schedule"],
            "reminder_ids": [
                row["id"] for row in result["reminders"] if row["id"] in reminder_ids
            ],
        }

    def _acknowledge_reminder(self, p, expected):
        reminder = self._row("reminders", p["reminder_id"])
        if reminder["status"] == "cancelled":
            raise ApplicationError("INVALID_STATE", "Cancelled reminder cannot be acknowledged")
        if reminder["status"] != "acknowledged":
            self.connection.execute(
                "UPDATE reminders SET status='acknowledged' WHERE id=? AND status IN ('pending','missed','delivered')",
                (reminder["id"],),
            )
        return dict(self.connection.execute(
            "SELECT * FROM reminders WHERE id=?", (reminder["id"],)
        ).fetchone())

    def _audio_file(self, asset):
        if asset["kind"] != "audio" or asset["status"] != "ready":
            raise ApplicationError("VALIDATION", "Audio asset is not ready")
        relative = Path(asset["relative_path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in asset["relative_path"]:
            raise ApplicationError("VALIDATION", "Audio asset path is not a safe relative path")
        root = (Path(self.database.path).parent / "assets").resolve()
        lexical_path = root / relative
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
                raise ApplicationError("VALIDATION", "Audio asset path cannot use a link")
        candidate = lexical_path.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ApplicationError("VALIDATION", "Audio asset path escapes the asset store") from None
        try:
            if not candidate.is_file():
                raise OSError()
            content_hash = hashlib.sha256()
            size = 0
            with candidate.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(block)
                    content_hash.update(block)
                if size != asset["byte_size"] or content_hash.hexdigest() != asset["sha256"]:
                    raise OSError()
                if asset["media_type"].lower() not in {"audio/wav", "audio/x-wav"}:
                    raise ApplicationError(
                        "VALIDATION", "This import path currently accepts decoded WAV audio only"
                    )
                stream.seek(0)
                with wave.open(stream, "rb") as source:
                    channels = source.getnchannels()
                    sample_width = source.getsampwidth()
                    sample_rate = source.getframerate()
                    frames = source.getnframes()
                    if channels < 1 or sample_width < 1 or sample_rate < 1 or frames < 1:
                        raise OSError()
                    remaining = frames
                    while remaining:
                        chunk_frames = min(remaining, 65536)
                        decoded = source.readframes(chunk_frames)
                        if len(decoded) != chunk_frames * channels * sample_width:
                            raise OSError()
                        remaining -= chunk_frames
                    duration_ms = frames * 1000 // sample_rate
            if duration_ms < 1:
                raise OSError()
            return candidate, duration_ms
        except ApplicationError:
            raise
        except (OSError, EOFError, wave.Error, ValueError):
            raise ApplicationError(
                "VALIDATION", "Audio asset is missing, damaged, or not decodable"
            ) from None

    def prepare_command(self, command, payload):
        if command != "AttachAudioImport":
            return None
        # Expensive filesystem reads run before ApplicationService opens its
        # BEGIN IMMEDIATE transaction. The handler rechecks asset identity and
        # state under the write lock before creating any durable rows.
        asset = self._row("file_assets", payload["asset_id"])
        path, duration_ms = self._audio_file(asset)
        stat = path.stat()
        return {
            "asset_id": asset["id"],
            "sha256": asset["sha256"],
            "relative_path": asset["relative_path"],
            "byte_size": asset["byte_size"],
            "file_identity": (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns),
            "duration_ms": duration_ms,
        }

    def _attach_audio_import(self, p, expected, prepared):
        if expected is not None:
            raise ApplicationError("VALIDATION", "Audio import does not use expected_revision")
        interview = self._row("interviews", p["interview_id"])
        asset = self._row("file_assets", p["asset_id"])
        if (
            prepared["asset_id"] != asset["id"]
            or prepared["sha256"] != asset["sha256"]
            or prepared["relative_path"] != asset["relative_path"]
            or prepared["byte_size"] != asset["byte_size"]
            or asset["status"] != "ready"
        ):
            raise ApplicationError(
                "INVALID_STATE", "Audio asset changed during validation; retry the import"
            )
        validated_path = (Path(self.database.path).parent / "assets" / asset["relative_path"]).resolve()
        try:
            validated_path.relative_to((Path(self.database.path).parent / "assets").resolve())
            current = validated_path.stat()
        except (OSError, ValueError):
            raise ApplicationError(
                "INVALID_STATE", "Audio file changed during validation; retry the import"
            ) from None
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != prepared["file_identity"]:
            raise ApplicationError(
                "INVALID_STATE", "Audio file changed during validation; retry the import"
            )
        duration_ms = prepared["duration_ms"]

        previous = self.connection.execute(
            "SELECT aa.id AS audio_asset_id, tj.task_id FROM audio_parts ap "
            "JOIN audio_assets aa ON aa.id=ap.audio_asset_id "
            "LEFT JOIN transcription_jobs tj ON tj.audio_asset_id=aa.id "
            "WHERE ap.file_asset_id=?",
            (asset["id"],),
        ).fetchone()
        if previous:
            if self._row("audio_assets", previous["audio_asset_id"])["interview_id"] != interview["id"]:
                raise ApplicationError("INVALID_STATE", "Audio asset is already attached to another interview")
            if previous["task_id"] is None:
                raise ApplicationError(
                    "STORAGE_ERROR", "Audio attachment is incomplete and requires recovery"
                )
            return {
                "audio_asset_id": previous["audio_asset_id"],
                "task_id": previous["task_id"],
                "status": self._row("background_tasks", previous["task_id"])["status"],
                "created": False,
            }

        config = {
            "engine": "local",
            "engine_version": "unconfigured",
            "model_asset_hash": None,
            "language": "auto",
            "chunking": {"strategy": "engine_default"},
            "speaker_options": {"enabled": False},
            "revision": 1,
        }
        config_hash = digest(config)
        audio_id, task_id, now = new_id(), new_id(), utc_now()
        dedup_key = f"transcribe:{audio_id}:1:{config_hash}:1"
        self._insert(
            "audio_assets",
            id=audio_id,
            interview_id=interview["id"],
            revision=1,
            origin="import",
            status="finalized",
            consent_at=None,
            duration_ms=duration_ms,
            completeness="complete",
            created_at=now,
            finalized_at=now,
        )
        self._insert(
            "audio_parts",
            audio_asset_id=audio_id,
            ordinal=0,
            file_asset_id=asset["id"],
            start_ms=0,
            end_ms=duration_ms,
        )
        # The persistent task is recorded immediately. With no model/worker
        # configured it is visible as needs_attention, never falsely running.
        self._insert(
            "background_tasks",
            id=task_id,
            kind="transcribe",
            dedup_key=dedup_key,
            input_json=json_text(
                {"schema_version": 1, "audio_asset_id": audio_id, "config_hash": config_hash}
            ),
            status="needs_attention",
            attempt=0,
            failure_count=0,
            owner_run_id=None,
            heartbeat_at=None,
            next_retry_at=None,
            checkpoint_asset_id=None,
            progress=0,
            stage="waiting_for_local_model",
            last_error_json=json_text(
                {
                    "code": "MODEL_NOT_READY",
                    "message": "No local transcription model is configured",
                    "retryable": False,
                }
            ),
            result_json=None,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        self._insert(
            "transcription_jobs",
            task_id=task_id,
            audio_asset_id=audio_id,
            asset_revision=1,
            config_hash=config_hash,
            config_json=json_text(config),
            request_generation=1,
            result_version_id=None,
        )
        return {
            "audio_asset_id": audio_id,
            "task_id": task_id,
            "status": "needs_attention",
            "created": True,
        }


    def interview_detail(self, identifier):
        interview = self._row("interviews", identifier)
        reminders = [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM reminders WHERE interview_id=? ORDER BY scheduled_for,id",
                (identifier,),
            )
        ]
        audio_assets = []
        for row in self.connection.execute(
            "SELECT * FROM audio_assets WHERE interview_id=? ORDER BY revision,id",
            (identifier,),
        ):
            audio = dict(row)
            audio["parts"] = [
                dict(part)
                for part in self.connection.execute(
                    "SELECT ap.*,fa.original_name,fa.media_type,fa.byte_size,fa.sha256 "
                    "FROM audio_parts ap JOIN file_assets fa ON fa.id=ap.file_asset_id "
                    "WHERE ap.audio_asset_id=? ORDER BY ap.ordinal",
                    (row["id"],),
                )
            ]
            job = self.connection.execute(
                "SELECT tj.*,bt.status AS task_status,bt.progress,bt.stage,bt.last_error_json "
                "FROM transcription_jobs tj JOIN background_tasks bt ON bt.id=tj.task_id "
                "WHERE tj.audio_asset_id=? ORDER BY tj.request_generation DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            audio["transcription"] = dict(job) if job else None
            audio_assets.append(audio)
        return {
            "schedule": interview,
            "current_context": None,
            "reminders": reminders,
            "contexts": [],
            "audio_assets": audio_assets,
            "current_transcript": None,
            "transcript_versions": [],
            "reports": [],
            "improvements": [],
        }

    def reminder_view(self, row):
        result = dict(row)
        if row.get("interview_id"):
            result["interview"] = self._row("interviews", row["interview_id"])
        else:
            # Cooldown reminders are part of the shared schema but not managed
            # by the interview schedule slice.
            result["interview"] = None
        return result

    def _import_job(self, p, expected):
        if expected is not None:
            raise ApplicationError("VALIDATION", "Import creates a new manual record")
        if "url" in p:
            public_url(text(p["url"], "url"))
            raise ApplicationError(
                "SOURCE_UNAVAILABLE", "尚未安装可读取此链接的来源，请粘贴岗位原文"
            )
        fields = structured(
            p["text_fields"],
            "title company url locations salary_raw experience_raw education_raw responsibilities requirements",
            "text_fields",
            versioned=False,
        )
        locations = fields.get("locations", [])
        if not isinstance(locations, list) or any(
            not isinstance(x, str) or not x.strip() for x in locations
        ):
            raise ApplicationError("VALIDATION", "locations must be a list of cities")
        optional = {
            key: fields.get(key)
            for key in (
                "salary_raw",
                "experience_raw",
                "education_raw",
                "responsibilities",
                "requirements",
            )
        }
        for key, value in optional.items():
            if value is not None:
                text(value, key)
        record = JobRecord(
            source_key="manual",
            source_job_id=new_id(),
            source_url=public_url(fields.get("url")),
            title=text(fields.get("title"), "title"),
            company=text(fields.get("company"), "company"),
            fetched_at=utc_now(),
            fetch_method="manual",
            locations=tuple(locations),
            **optional,
        )
        result = self.jobs.write_observation(record)
        return self.job_detail(result.job_id)

    def job_detail(self, identifier):
        job = self._row("jobs", identifier)
        result = self.jobs.details(job["source_key"], job["external_key"])
        result["source_key"] = job["source_key"]
        observation = self.connection.execute(
            "SELECT * FROM job_observations WHERE job_id=? ORDER BY rowid DESC LIMIT 1",
            (identifier,),
        ).fetchone()
        result["current_observation"] = decoded(observation)
        result["versions"] = [
            decoded(v)
            for v in self.connection.execute(
                "SELECT * FROM job_versions WHERE job_id=? ORDER BY revision DESC",
                (identifier,),
            )
        ]
        result["opportunities"] = [
            self.get_opportunity(r[0])
            for r in self.connection.execute(
                "SELECT opportunity_id FROM opportunity_jobs WHERE job_id=?",
                (identifier,),
            )
        ]
        # HTTP views and persisted command receipts share JSON-compatible types.
        return json.loads(json_text(result))

    def opportunity_detail(self, identifier):
        result = self.get_opportunity(identifier)
        result["jobs"] = [self.job_detail(job_id) for job_id in result["job_ids"]]
        result["cooldown"] = self._cooldown_snapshot(identifier)
        result["preparations"] = [
            self.preparation_detail(r[0])
            for r in self.connection.execute(
                "SELECT id FROM application_preparations WHERE opportunity_id=? ORDER BY created_at DESC,id",
                (identifier,),
            )
        ]
        result["applications"] = [
            self.get_application(r[0])
            for r in self.connection.execute(
                "SELECT id FROM applications WHERE opportunity_id=? ORDER BY created_at DESC,id",
                (identifier,),
            )
        ]
        result["feedback"] = []
        result["interviews"] = [
            self.interview_detail(row[0])
            for row in self.connection.execute(
                "SELECT id FROM interviews WHERE opportunity_id=? ORDER BY starts_at IS NULL,starts_at,id",
                (identifier,),
            )
        ]
        return result

    def preparation_detail(self, identifier):
        result = self.get_preparation(identifier)
        result["job"] = decoded(self._row("job_versions", result["job_version_id"]))
        result["resume"] = (
            self.get_material_version(result["resume_version_id"])
            if result["resume_version_id"]
            else None
        )
        return result

    def _page(
        self, table, params, *, where="1", values=(), transform=decoded, context=""
    ):
        try:
            limit = int(params.get("limit", "30"))
            if not 1 <= limit <= 100:
                raise ValueError()
            query_hash = digest(
                {"table": table, "where": where, "values": values, "context": context}
            )
            last = self.connection.execute(
                f"SELECT COALESCE(MAX(rowid),0)+1 FROM {table}"
            ).fetchone()[0]
            as_of = utc_now()
            if params.get("cursor"):
                cursor = json.loads(base64.urlsafe_b64decode(params["cursor"]))
                if (
                    set(cursor) != {"q", "last", "as_of"}
                    or cursor["q"] != query_hash
                    or type(cursor["last"]) is not int
                    or cursor["last"] < 0
                ):
                    raise ValueError()
                last, as_of = cursor["last"], cursor["as_of"]
            rows = self.connection.execute(
                f"SELECT rowid AS _position,* FROM {table} WHERE ({where}) AND rowid<? ORDER BY rowid DESC LIMIT ?",
                (*values, last, limit + 1),
            ).fetchall()
            next_cursor = None
            if len(rows) > limit:
                next_cursor = base64.urlsafe_b64encode(
                    json_text(
                        {
                            "q": query_hash,
                            "last": rows[limit - 1]["_position"],
                            "as_of": as_of,
                        }
                    ).encode()
                ).decode()
            items = []
            for row in rows[:limit]:
                item = dict(row)
                item.pop("_position")
                items.append(transform(item))
            return {"items": items, "next_cursor": next_cursor, "as_of": as_of}
        except (ValueError, TypeError, KeyError):
            raise ApplicationError(
                "VALIDATION", "Invalid pagination parameters"
            ) from None

    def query(self, path, params=None):
        params = dict(params or {})
        if set(params) - {
            "limit",
            "cursor",
            "query",
            "status",
            "source_key",
            "completeness",
            "from",
            "to",
        }:
            raise ApplicationError("VALIDATION", "Unknown query parameters")
        parts = path.strip("/").split("/")
        if parts == ["profile"]:
            materials = []
            for row in self.connection.execute(
                "SELECT * FROM materials ORDER BY created_at DESC,id"
            ):
                material = dict(row)
                latest = self.connection.execute(
                    "SELECT id FROM material_versions WHERE material_id=? ORDER BY revision DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                material["latest_version"] = (
                    self.get_material_version(latest[0]) if latest else None
                )
                materials.append(material)
            return {
                "targets": [
                    decoded(r)
                    for r in self.connection.execute(
                        "SELECT * FROM profile_targets ORDER BY created_at DESC,id"
                    )
                ],
                "facts": [
                    decoded(r)
                    for r in self.connection.execute(
                        "SELECT * FROM profile_facts ORDER BY created_at DESC,id"
                    )
                ],
                "materials": materials,
            }
        if len(parts) == 3 and parts[0] == "materials" and parts[2] == "versions":
            self._row("materials", parts[1])
            return self._page(
                "material_versions",
                params,
                where="material_id=?",
                values=(parts[1],),
                transform=lambda r: self.get_material_version(r["id"]),
            )
        if len(parts) == 2 and parts[0] in {
            "jobs",
            "opportunities",
            "preparations",
            "applications",
            "interviews",
        }:
            return {
                "jobs": self.job_detail,
                "opportunities": self.opportunity_detail,
                "preparations": self.preparation_detail,
                "applications": self.get_application,
                "interviews": self.interview_detail,
            }[parts[0]](parts[1])
        if parts == ["interviews"]:
            where, values = ["1"], []
            if params.get("status"):
                choice(params["status"], {"planned", "completed", "cancelled"}, "status")
                where.append("status=?")
                values.append(params["status"])
            if params.get("from"):
                try:
                    start = utc_time(params["from"])
                except (ValueError, TypeError):
                    raise ApplicationError("VALIDATION", "Invalid from timestamp") from None
                where.append("starts_at>=?")
                values.append(start)
            if params.get("to"):
                try:
                    end = utc_time(params["to"])
                except (ValueError, TypeError):
                    raise ApplicationError("VALIDATION", "Invalid to timestamp") from None
                where.append("starts_at<?")
                values.append(end)
                if params.get("from") and end <= start:
                    raise ApplicationError("VALIDATION", "to must be later than from")
            return self._page(
                "interviews",
                params,
                where=" AND ".join(where),
                values=tuple(values),
                transform=lambda row: self.interview_detail(row["id"]),
            )
        if parts == ["reminders"]:
            where, values = ["1"], []
            if params.get("status"):
                choice(
                    params["status"],
                    {"pending", "delivered", "missed", "cancelled", "acknowledged"},
                    "status",
                )
                where.append("status=?")
                values.append(params["status"])
            return self._page(
                "reminders",
                params,
                where=" AND ".join(where),
                values=tuple(values),
                transform=self.reminder_view,
            )
        if parts == ["jobs"]:
            where, values = ["1"], []
            for key, column in (("source_key", "source_key"),):
                if params.get(key):
                    where.append(f"{column}=?")
                    values.append(params[key])
            if params.get("query"):
                where.append(
                    "current_version_id IN (SELECT id FROM job_versions WHERE instr(title,?)>0 OR instr(company_name,?)>0)"
                )
                values.extend([params["query"]] * 2)
            if params.get("completeness"):
                where.append(
                    "current_version_id IN (SELECT id FROM job_versions WHERE completeness=?)"
                )
                values.append(params["completeness"])
            return self._page(
                "jobs",
                params,
                where=" AND ".join(where),
                values=tuple(values),
                transform=lambda r: {
                    "id": r["id"],
                    "source_key": r["source_key"],
                    "last_observed_at": r["last_observed_at"],
                    "current_version": decoded(
                        self._row("job_versions", r["current_version_id"])
                    ),
                },
            )
        if parts == ["opportunities"]:
            where, values = ["1"], []
            if params.get("query"):
                where.append("(instr(title,?)>0 OR instr(company_name,?)>0)")
                values.extend([params["query"]] * 2)
            if params.get("status"):
                choice(
                    params["status"],
                    {
                        "saved", "deferred", "applying", "applied", "interviewing",
                        "offer", "rejected", "withdrawn", "archived",
                    },
                    "status",
                )
                where.append("status=?")
                values.append(params["status"])
            return self._page(
                "opportunities",
                params,
                where=" AND ".join(where),
                values=tuple(values),
                transform=lambda r: self.get_opportunity(r["id"]),
            )
        if parts == ["sources"]:
            # No product adapter installed in this slice. Manual records are not
            # advertised as a searchable source or an installed platform.
            return {"items": [], "next_cursor": None, "as_of": utc_now()}
        raise ApplicationError("NOT_FOUND", "Query endpoint is not available")
