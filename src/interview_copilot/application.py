"""Transactional application commands for the first local storage slice.

No network, microphone or submission tools are reachable from this service.
An HTTP adapter can translate ApplicationError without duplicating these rules.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID

from .storage import Database
from .storage.database import digest, json_text, new_id, utc_now, utc_time


class ApplicationError(ValueError):
    def __init__(self, code, message, *, details=None, retryable=False):
        super().__init__(message)
        self.code, self.details, self.retryable = code, details or {}, retryable


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApplicationError("VALIDATION", f"{field} must contain text")
    return value


def choice(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise ApplicationError("VALIDATION", f"Invalid {field}")
    return value


def structured(value, fields, name, *, versioned=True):
    allowed = set(fields.split()) | ({"schema_version"} if versioned else set())
    if not isinstance(value, dict) or set(value) - allowed:
        raise ApplicationError("VALIDATION", f"Invalid fields in {name}")
    if versioned:
        version = value.get("schema_version", 1)
        if type(version) is not int or version != 1:
            raise ApplicationError("VALIDATION", f"Unsupported {name} schema version")
        return {**value, "schema_version": 1}
    return dict(value)


def public_url(value):
    if value is None:
        return None
    parts = urlsplit(text(value, "apply_url"))
    if (
        parts.scheme not in {"https", "http"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise ApplicationError(
            "VALIDATION", "Only ordinary HTTP(S) application links are allowed"
        )
    return value


class ApplicationService:
    def __init__(self, database: Database):
        self.database = database
        self.connection = database.connection
        # Explicit command whitelist; there is deliberately no SubmitApplication.
        self.commands = {
            "SaveTarget": (self._target, "id label criteria active"),
            "SaveFact": (self._fact, "id kind content provenance"),
            "ConfirmFact": (self._confirm_fact, "id"),
            "ImportMaterial": (
                self._import_material,
                "material_id label asset_id text",
            ),
            "SaveMaterialVersion": (
                self._material_version,
                "material_id parent_version_id text fact_ids",
            ),
            "SaveOpportunity": (self._opportunity, "job_id title company_name"),
            "UpdateOpportunity": (self._update_opportunity, "id status note title"),
            "LinkJob": (self._link_job, "opportunity_id job_id basis"),
            "UnlinkJob": (self._unlink_job, "opportunity_id job_id basis"),
            "RecordCooldown": (
                self._cooldown,
                "opportunity_id scope status explanation evidence known_until supersedes_id",
            ),
            "SavePreparation": (
                self._preparation,
                "id opportunity_id job_version_id resume_version_id resume_exception channel apply_url",
            ),
            "ConfirmPreparation": (self._confirm, "preparation_id step"),
            "DeferPreparation": (self._defer, "preparation_id"),
            "RecordApplication": (
                self._application,
                "id opportunity_id preparation_id job_version_id resume_version_id channel outcome submitted_at evidence reason",
            ),
        }

    def execute(self, request_id, command, payload, *, expected_revision=None):
        if not isinstance(command, str) or command not in self.commands:
            raise ApplicationError(
                "UNKNOWN_COMMAND",
                "Command is not available in this application service",
            )
        handler, allowed = self.commands[command]
        try:
            request_id = str(UUID(request_id))
            if not isinstance(payload, dict) or set(payload) - set(allowed.split()):
                raise ApplicationError("VALIDATION", "Unknown command fields")
            if expected_revision is not None and (
                type(expected_revision) is not int or expected_revision < 1
            ):
                raise ApplicationError(
                    "VALIDATION", "expected_revision must be a positive integer"
                )
            fingerprint = digest(
                {
                    "command": command,
                    "input": payload,
                    "expected_revision": expected_revision,
                }
            )
            # Fast-path durable replays before expensive preflight work (e.g.
            # hashing a large audio file). The receipt is checked again inside
            # the write transaction to close races with concurrent requests.
            prior = self.connection.execute(
                "SELECT * FROM command_receipts WHERE request_id=?", (request_id,)
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != fingerprint:
                    raise ApplicationError(
                        "REQUEST_ID_REUSED",
                        "This request ID belongs to different input",
                    )
                return json.loads(prior["response_json"])
            prepared = self.prepare_command(command, payload)
            self.verify_prepared_command(command, payload, prepared)
            with self.database.transaction():
                prior = self.connection.execute(
                    "SELECT * FROM command_receipts WHERE request_id=?", (request_id,)
                ).fetchone()
                if prior is not None:
                    if prior["request_hash"] != fingerprint:
                        raise ApplicationError(
                            "REQUEST_ID_REUSED",
                            "This request ID belongs to different input",
                        )
                    return json.loads(prior["response_json"])
                if prepared is None:
                    data = handler(payload, expected_revision)
                else:
                    data = handler(payload, expected_revision, prepared)
                result = {"data": data, "request_id": request_id}
                self._insert(
                    "command_receipts",
                    request_id=request_id,
                    command=command,
                    request_hash=fingerprint,
                    response_json=json_text(result),
                    created_at=utc_now(),
                )
                return result
        except ApplicationError:
            raise
        except sqlite3.IntegrityError:
            raise ApplicationError(
                "STORAGE_CONSTRAINT",
                "The command could not be saved; all changes were rolled back",
            ) from None
        except sqlite3.OperationalError as error:
            if "locked" in str(error) or "busy" in str(error):
                raise ApplicationError(
                    "BUSY",
                    "Local storage is busy; retry the same request",
                    retryable=True,
                ) from None
            raise ApplicationError(
                "STORAGE_ERROR", "Local storage could not complete the command"
            ) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ApplicationError("VALIDATION", "Invalid command input") from None

    def prepare_command(self, command, payload):
        """Perform slow, side-effect-free command validation before the write lock."""
        return None

    def verify_prepared_command(self, command, payload, prepared):
        """Recheck external identities immediately before acquiring the write lock."""
        return None

    def _insert(self, table, **fields):
        # Table and column names come exclusively from the explicit methods below.
        self.connection.execute(
            f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
            tuple(fields.values()),
        )

    def _row(self, table, identifier):
        text(identifier, "id")
        try:
            identifier = str(UUID(identifier))
        except ValueError:
            raise ApplicationError("VALIDATION", "id must be a UUID") from None
        row = self.connection.execute(
            f"SELECT * FROM {table} WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ApplicationError("NOT_FOUND", f"No {table} record with that ID")
        return dict(row)

    def _expected(self, table, identifier, expected):
        row = self._row(table, identifier)
        if expected is None or expected != row["revision"]:
            raise ApplicationError(
                "REVISION_CONFLICT",
                "Record changed; reload before editing",
                details={"revision": row["revision"]},
            )
        return row

    def _update(self, table, identifier, expected, **fields):
        assignments = ",".join(f"{column}=?" for column in fields)
        cursor = self.connection.execute(
            f"UPDATE {table} SET {assignments},revision=revision+1,updated_at=? WHERE id=? AND revision=?",
            (*fields.values(), utc_now(), identifier, expected),
        )
        if cursor.rowcount != 1:
            raise ApplicationError(
                "REVISION_CONFLICT", "Record changed; reload before editing"
            )

    def _asset(self, identifier, kind=None):
        asset = self._row("file_assets", identifier)
        if asset["status"] != "ready" or (kind and asset["kind"] != kind):
            raise ApplicationError(
                "VALIDATION", "Asset is not ready for this operation"
            )
        return asset

    def _target(self, p, expected):
        criteria = structured(
            p["criteria"], "keywords cities any_city conditions", "criteria"
        )
        keywords, cities, any_city = (
            criteria.get("keywords"),
            criteria.get("cities", []),
            criteria.get("any_city", False),
        )
        if (
            not isinstance(keywords, list)
            or not keywords
            or not all(isinstance(k, str) and k.strip() for k in keywords)
        ):
            raise ApplicationError("VALIDATION", "Target needs keywords")
        if (
            type(any_city) is not bool
            or not isinstance(cities, list)
            or not all(isinstance(c, str) and c.strip() for c in cities)
            or bool(cities) == any_city
        ):
            raise ApplicationError(
                "VALIDATION", "Choose cities or explicitly choose any city"
            )
        if not isinstance(criteria.get("conditions", []), list):
            raise ApplicationError("VALIDATION", "conditions must be a list")
        for condition in criteria.get("conditions", []):
            condition = structured(
                condition,
                "field operator value importance",
                "condition",
                versioned=False,
            )
            text(condition.get("field"), "condition.field")
            text(condition.get("operator"), "condition.operator")
            choice(
                condition.get("importance"), {"must", "prefer"}, "condition.importance"
            )
            value = condition["value"]
            if condition["field"] == "salary" or isinstance(value, dict):
                money = structured(
                    value, "amount currency period", "money", versioned=False
                )
                if type(money.get("amount")) not in (int, float) or money["amount"] < 0:
                    raise ApplicationError(
                        "VALIDATION", "Amount must be a nonnegative number"
                    )
                currency = text(money.get("currency"), "currency")
                if (
                    len(currency) != 3
                    or not currency.isascii()
                    or not currency.isupper()
                    or not currency.isalpha()
                ):
                    raise ApplicationError(
                        "VALIDATION", "Currency must be a three-letter code"
                    )
                choice(money.get("period"), {"hour", "day", "month", "year"}, "period")
            elif value is None or (
                isinstance(value, list)
                and any(type(v) not in (str, int, float, bool) for v in value)
            ):
                raise ApplicationError(
                    "VALIDATION", "Condition value must contain comparable values"
                )
        active = p.get("active", True)
        if type(active) is not bool:
            raise ApplicationError("VALIDATION", "active must be boolean")
        fields = dict(
            label=text(p.get("label"), "label"),
            criteria_json=json_text({**criteria, "schema_version": 1}),
            active=int(active),
        )
        if p.get("id"):
            row = self._expected("profile_targets", p["id"], expected)
            self._update("profile_targets", row["id"], expected, **fields)
            identifier = row["id"]
        else:
            identifier = new_id()
            now = utc_now()
            self._insert(
                "profile_targets",
                id=identifier,
                **fields,
                created_at=now,
                updated_at=now,
            )
        return self._row("profile_targets", identifier)

    def _fact(self, p, expected):
        kind = choice(
            p.get("kind"),
            {"employment", "project", "skill", "education", "achievement"},
            "kind",
        )
        content = structured(
            p["content"],
            "title description start_date end_date organization result",
            "content",
        )
        provenance = structured(
            p["provenance"], "kind material_version_id quote confirmed_by", "provenance"
        )
        text(content.get("title"), "content.title")
        text(content.get("description"), "content.description")
        for field in ("organization", "result"):
            if field in content:
                text(content[field], field)
        for field in ("start_date", "end_date"):
            if field in content:
                content[field] = date.fromisoformat(
                    text(content[field], field)
                ).isoformat()
        if (
            content.get("start_date")
            and content.get("end_date")
            and content["end_date"] < content["start_date"]
        ):
            raise ApplicationError("VALIDATION", "Fact end date precedes start date")
        choice(provenance.get("kind"), {"user", "material_extract"}, "provenance.kind")
        if "confirmed_by" in provenance:
            choice(provenance["confirmed_by"], {"user"}, "confirmed_by")
        if (
            provenance["kind"] == "material_extract"
            or "material_version_id" in provenance
        ):
            material = self._row(
                "material_versions",
                text(provenance.get("material_version_id"), "material_version_id"),
            )
            quote = text(provenance.get("quote"), "quote")
            if quote not in material["text_content"]:
                raise ApplicationError(
                    "VALIDATION",
                    "Quote is not present in the referenced material version",
                )
        elif "quote" in provenance:
            text(provenance["quote"], "quote")
        fields = dict(
            kind=kind,
            content_json=json_text({**content, "schema_version": 1}),
            provenance_json=json_text({**provenance, "schema_version": 1}),
            status="draft",
            confirmed_at=None,
        )
        if p.get("id"):
            row = self._expected("profile_facts", p["id"], expected)
            identifier = row["id"]
            self._update("profile_facts", identifier, expected, **fields)
        else:
            identifier = new_id()
            now = utc_now()
            self._insert(
                "profile_facts", id=identifier, **fields, created_at=now, updated_at=now
            )
        return self._row("profile_facts", identifier)

    def _confirm_fact(self, p, expected):
        row = self._expected("profile_facts", p["id"], expected)
        if row["status"] != "draft":
            raise ApplicationError(
                "INVALID_STATE", "Only a draft fact can be confirmed"
            )
        self._update(
            "profile_facts",
            row["id"],
            expected,
            status="confirmed",
            confirmed_at=utc_now(),
        )
        return self._row("profile_facts", row["id"])

    def _save_version(self, material_id, content, facts, asset_id=None):
        text(content, "text")
        if asset_id:
            self._asset(asset_id, "resume")
        version = new_id()
        revision = self.connection.execute(
            "SELECT COALESCE(MAX(revision),0)+1 FROM material_versions WHERE material_id=?",
            (material_id,),
        ).fetchone()[0]
        snapshot = {"schema_version": 1, "facts": facts, "generation": {}}
        self._insert(
            "material_versions",
            id=version,
            material_id=material_id,
            revision=revision,
            file_asset_id=asset_id,
            text_content=content,
            content_hash=digest(
                {"text": content, "facts": facts, "asset_id": asset_id}
            ),
            fact_snapshot_json=json_text(snapshot),
            created_at=utc_now(),
        )
        return self.get_material_version(version)

    def _import_material(self, p, expected):
        if p.get("material_id"):
            material = self._row("materials", p["material_id"])
            if material["archived_at"]:
                raise ApplicationError("INVALID_STATE", "Material is archived")
            identifier = material["id"]
        else:
            identifier = new_id()
            self._insert(
                "materials",
                id=identifier,
                label=text(p.get("label"), "label"),
                created_at=utc_now(),
            )
        return self._save_version(identifier, p["text"], [], p.get("asset_id"))

    def _material_version(self, p, expected):
        material = self._row("materials", p["material_id"])
        if material["archived_at"]:
            raise ApplicationError("INVALID_STATE", "Material is archived")
        latest = self.connection.execute(
            "SELECT id FROM material_versions WHERE material_id=? ORDER BY revision DESC LIMIT 1",
            (material["id"],),
        ).fetchone()
        if latest is None or latest[0] != p.get("parent_version_id"):
            raise ApplicationError(
                "REVISION_CONFLICT",
                "Resume was revised; reload before editing",
                details={"parent_version_id": latest[0] if latest else None},
            )
        identifiers = p.get("fact_ids", [])
        if not isinstance(identifiers, list) or len(set(identifiers)) != len(
            identifiers
        ):
            raise ApplicationError("VALIDATION", "fact_ids must be unique IDs")
        facts = []
        for identifier in identifiers:
            fact = self._row("profile_facts", identifier)
            if fact["status"] != "confirmed":
                raise ApplicationError("VALIDATION", "Only confirmed facts may be used")
            facts.append(
                {
                    "id": fact["id"],
                    "revision": fact["revision"],
                    "content": json.loads(fact["content_json"]),
                }
            )
        return self._save_version(material["id"], p["text"], facts)

    def _opportunity(self, p, expected):
        job = None
        if p.get("job_id"):
            job = self._row("jobs", p["job_id"])
            existing = self.connection.execute(
                "SELECT opportunity_id FROM opportunity_jobs WHERE job_id=? ORDER BY created_at LIMIT 1",
                (job["id"],),
            ).fetchone()
            if existing:
                return self.get_opportunity(existing[0])
            version = self._row("job_versions", job["current_version_id"])
            title, company = version["title"], version["company_name"]
        else:
            title, company = text(p.get("title"), "title"), text(
                p.get("company_name"), "company_name"
            )
        identifier = new_id()
        now = utc_now()
        self._insert(
            "opportunities",
            id=identifier,
            title=title,
            company_name=company,
            created_at=now,
            updated_at=now,
        )
        if job:
            self._insert(
                "opportunity_jobs",
                opportunity_id=identifier,
                job_id=job["id"],
                basis_json=json_text(
                    {
                        "schema_version": 1,
                        "kind": "user_confirmed",
                        "description": "User saved this job as an opportunity",
                        "confirmed_at": now,
                    }
                ),
                created_at=now,
            )
        return self.get_opportunity(identifier)

    def _update_opportunity(self, p, expected):
        row = self._expected("opportunities", p["id"], expected)
        fields = {k: p[k] for k in ("status", "note", "title") if k in p}
        if "status" in fields:
            choice(
                fields["status"],
                {
                    "saved",
                    "deferred",
                    "applying",
                    "applied",
                    "interviewing",
                    "offer",
                    "rejected",
                    "withdrawn",
                    "archived",
                },
                "status",
            )
        if "title" in fields:
            text(fields["title"], "title")
        if "note" in fields and not isinstance(fields["note"], str):
            raise ApplicationError("VALIDATION", "note must be text")
        if fields:
            self._update("opportunities", row["id"], expected, **fields)
        return self.get_opportunity(row["id"])

    def _basis(self, value):
        basis = structured(value, "kind description confirmed_at", "basis")
        choice(basis.get("kind"), {"user_confirmed"}, "basis.kind")
        text(basis.get("description"), "basis.description")
        basis["confirmed_at"] = (
            utc_time(basis["confirmed_at"]) if "confirmed_at" in basis else utc_now()
        )
        return basis

    def _link_job(self, p, expected):
        row = self._expected("opportunities", p["opportunity_id"], expected)
        self._row("jobs", p["job_id"])
        basis = self._basis(p.get("basis"))
        self.connection.execute(
            "INSERT INTO opportunity_jobs VALUES(?,?,?,?) ON CONFLICT(opportunity_id,job_id) DO NOTHING",
            (row["id"], p["job_id"], json_text(basis), utc_now()),
        )
        self._update("opportunities", row["id"], expected, note=row["note"])
        return self.get_opportunity(row["id"])

    def _unlink_job(self, p, expected):
        row = self._expected("opportunities", p["opportunity_id"], expected)
        self._row("jobs", p["job_id"])
        self._basis(p.get("basis"))
        removed = self.connection.execute(
            "DELETE FROM opportunity_jobs WHERE opportunity_id=? AND job_id=?",
            (row["id"], p["job_id"]),
        )
        if removed.rowcount:
            # Invalidate the user's previous confirmations in the same transaction
            # as the association change. Used preparations remain historical input;
            # their availability for future actions is checked separately.
            self.connection.execute(
                """UPDATE application_preparations
                   SET material_confirmed_at=NULL, cooldown_confirmed_at=NULL,
                       status=CASE WHEN status='deferred' THEN 'deferred' ELSE 'draft' END,
                       revision=revision+1, updated_at=?
                   WHERE opportunity_id=?
                     AND job_version_id IN (SELECT id FROM job_versions WHERE job_id=?)
                     AND NOT EXISTS (
                         SELECT 1 FROM applications a
                         WHERE a.preparation_id=application_preparations.id
                     )""",
                (utc_now(), row["id"], p["job_id"]),
            )
        self._update("opportunities", row["id"], expected, note=row["note"])
        return self.get_opportunity(row["id"])

    def _cooldown_snapshot(self, opportunity_id):
        row = self.connection.execute(
            "SELECT * FROM cooldown_notes WHERE opportunity_id=? ORDER BY rowid DESC LIMIT 1",
            (opportunity_id,),
        ).fetchone()
        if row is None:
            return {
                "schema_version": 1,
                "note_ids": [],
                "status": "unknown",
                "explanation": "冷却期尚未核实",
                "evidence": {"schema_version": 1, "items": []},
                "known_until": None,
            }
        return {
            "schema_version": 1,
            "note_ids": [row["id"]],
            "status": row["status"],
            "explanation": row["explanation"],
            "evidence": json.loads(row["evidence_json"]),
            "known_until": row["known_until"],
        }

    def _cooldown(self, p, expected):
        opportunity = self._expected("opportunities", p["opportunity_id"], expected)
        status = choice(p.get("status"), {"present", "absent", "unknown"}, "status")
        evidence = structured(p["evidence"], "items applicability_note", "evidence")
        if not isinstance(evidence.get("items"), list):
            raise ApplicationError("VALIDATION", "Cooldown evidence needs items")
        if "applicability_note" in evidence and not isinstance(
            evidence["applicability_note"], str
        ):
            raise ApplicationError("VALIDATION", "Applicability note must be text")
        evidence.setdefault("applicability_note", "")
        if status != "unknown" and not evidence["items"]:
            raise ApplicationError(
                "VALIDATION", "Present/absent cooldown requires evidence"
            )
        normalized_items = []
        for item in evidence["items"]:
            item = structured(
                item,
                "kind text url asset_id checked_at",
                "evidence item",
                versioned=False,
            )
            choice(item.get("kind"), {"user", "url", "document"}, "evidence.kind")
            text(item.get("text"), "evidence.text")
            if item["kind"] == "url":
                text(item.get("url"), "evidence.url")
            if item["kind"] == "document":
                text(item.get("asset_id"), "evidence.asset_id")
            if "url" in item:
                item["url"] = public_url(text(item["url"], "evidence.url"))
            if item.get("asset_id"):
                self._asset(item["asset_id"])
            item["checked_at"] = (
                utc_time(item["checked_at"]) if "checked_at" in item else utc_now()
            )
            normalized_items.append(item)
        evidence["items"] = normalized_items
        prior = self._cooldown_snapshot(opportunity["id"])["note_ids"]
        supersedes = p.get("supersedes_id", prior[0] if prior else None)
        if (
            supersedes
            and self._row("cooldown_notes", supersedes)["opportunity_id"]
            != opportunity["id"]
        ):
            raise ApplicationError(
                "VALIDATION", "Cooldown belongs to another opportunity"
            )
        identifier = new_id()
        self._insert(
            "cooldown_notes",
            id=identifier,
            opportunity_id=opportunity["id"],
            scope=choice(p.get("scope"), {"company", "job"}, "scope"),
            status=status,
            explanation=text(p.get("explanation"), "explanation"),
            evidence_json=json_text(evidence),
            known_until=utc_time(p["known_until"]) if p.get("known_until") else None,
            checked_at=utc_now(),
            supersedes_id=supersedes,
        )
        snapshot = self._cooldown_snapshot(opportunity["id"])
        self.connection.execute(
            "UPDATE application_preparations SET cooldown_status=?,cooldown_snapshot_json=?,material_confirmed_at=NULL,cooldown_confirmed_at=NULL,status='draft',revision=revision+1,updated_at=? WHERE opportunity_id=? AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.preparation_id=application_preparations.id)",
            (status, json_text(snapshot), utc_now(), opportunity["id"]),
        )
        self._update(
            "opportunities", opportunity["id"], expected, note=opportunity["note"]
        )
        return self._row("cooldown_notes", identifier)

    def _has_job_link(self, version_id, opportunity_id):
        return (
            self.connection.execute(
                """SELECT 1 FROM opportunity_jobs link
               JOIN job_versions version ON version.job_id=link.job_id
               WHERE link.opportunity_id=? AND version.id=?""",
                (opportunity_id, version_id),
            ).fetchone()
            is not None
        )

    def _job_for_opportunity(self, version_id, opportunity_id):
        version = self._row("job_versions", version_id)
        if not self._has_job_link(version_id, opportunity_id):
            raise ApplicationError(
                "VALIDATION", "Job is not linked to this opportunity"
            )
        return version

    def _preparation(self, p, expected):
        opportunity = self._row("opportunities", p["opportunity_id"])
        self._job_for_opportunity(p["job_version_id"], opportunity["id"])
        if p.get("resume_version_id"):
            self._row("material_versions", p["resume_version_id"])
        exception = p.get("resume_exception")
        if exception is not None and not isinstance(exception, str):
            raise ApplicationError("VALIDATION", "resume_exception must be text")
        snapshot = self._cooldown_snapshot(opportunity["id"])
        fields = dict(
            opportunity_id=opportunity["id"],
            job_version_id=p["job_version_id"],
            resume_version_id=p.get("resume_version_id"),
            resume_exception=exception,
            channel=text(p.get("channel"), "channel"),
            apply_url=public_url(p.get("apply_url")),
            cooldown_snapshot_json=json_text(snapshot),
            cooldown_status=snapshot["status"],
        )
        if p.get("id"):
            row = self._expected("application_preparations", p["id"], expected)
            identifier = row["id"]
            if row["opportunity_id"] != opportunity["id"]:
                raise ApplicationError(
                    "VALIDATION", "Cannot move preparation to another opportunity"
                )
            if (
                any(row[k] != value for k, value in fields.items())
                or row["status"] == "deferred"
            ):
                self._update(
                    "application_preparations",
                    identifier,
                    expected,
                    **fields,
                    status="draft",
                    material_confirmed_at=None,
                    cooldown_confirmed_at=None,
                )
        else:
            identifier = new_id()
            now = utc_now()
            self._insert(
                "application_preparations",
                id=identifier,
                **fields,
                created_at=now,
                updated_at=now,
            )
        return self.get_preparation(identifier)

    def _confirm(self, p, expected):
        row = self._expected("application_preparations", p["preparation_id"], expected)
        self._job_for_opportunity(row["job_version_id"], row["opportunity_id"])
        step = choice(p.get("step"), {"materials", "cooldown"}, "step")
        current = self.get_preparation(row["id"])
        if row["status"] != "draft" or current["next_step"] != step:
            raise ApplicationError(
                "INVALID_STATE", "This is not the current confirmation step"
            )
        if step == "materials":
            if not row["resume_version_id"]:
                text(row["resume_exception"], "resume_exception")
            self._update(
                "application_preparations",
                row["id"],
                expected,
                material_confirmed_at=utc_now(),
                status=(
                    "draft"
                    if row["cooldown_status"] == "present"
                    else "ready_for_manual_apply"
                ),
            )
        else:
            self._update(
                "application_preparations",
                row["id"],
                expected,
                cooldown_confirmed_at=utc_now(),
                status="ready_for_manual_apply",
            )
        return self.get_preparation(row["id"])

    def _defer(self, p, expected):
        row = self._expected("application_preparations", p["preparation_id"], expected)
        self._update("application_preparations", row["id"], expected, status="deferred")
        return self.get_preparation(row["id"])

    def _application(self, p, expected):
        opportunity = self._row("opportunities", p["opportunity_id"])
        old = self._expected("applications", p["id"], expected) if p.get("id") else None
        if old and old["opportunity_id"] != opportunity["id"]:
            raise ApplicationError("VALIDATION", "Cannot move an application")
        # A removed current association does not erase a historical fact. Keep
        # correcting that exact JD version, but require a link for a new choice.
        if old is None or p["job_version_id"] != old["job_version_id"]:
            self._job_for_opportunity(p["job_version_id"], opportunity["id"])
        if p.get("resume_version_id"):
            self._row("material_versions", p["resume_version_id"])
        preparation_id = p.get("preparation_id", old["preparation_id"] if old else None)
        if old and preparation_id == old["preparation_id"]:
            event = self.connection.execute(
                "SELECT snapshot_json FROM application_events WHERE application_id=? AND revision=?",
                (old["id"], old["revision"]),
            ).fetchone()
            if event is None:
                raise ApplicationError(
                    "STORAGE_ERROR",
                    "Application history is incomplete; cannot correct this record",
                )
            # The latest event carries the snapshot selected by the last explicit
            # association correction. Never resample the mutable preparation here.
            preparation = json.loads(event["snapshot_json"])["preparation"]
        else:
            preparation = (
                self.get_preparation(preparation_id) if preparation_id else None
            )
            if preparation:
                self._job_for_opportunity(
                    preparation["job_version_id"], opportunity["id"]
                )
        if preparation and preparation["opportunity_id"] != opportunity["id"]:
            raise ApplicationError(
                "VALIDATION", "Preparation belongs to another opportunity"
            )
        outcome = choice(
            p.get("outcome"), {"submitted", "unknown", "failed"}, "outcome"
        )
        submitted_at = utc_time(p["submitted_at"]) if p.get("submitted_at") else None
        if outcome == "submitted" and submitted_at is None:
            raise ApplicationError(
                "VALIDATION", "Submitted applications need their actual submission time"
            )
        evidence = structured(p.get("evidence"), "kind statement asset_ids", "evidence")
        kind = choice(
            evidence.get("kind"), {"user_attestation", "receipt"}, "evidence.kind"
        )
        asset_ids = evidence.get("asset_ids", [])
        if not isinstance(asset_ids, list):
            raise ApplicationError("VALIDATION", "asset_ids must be a list")
        if kind == "user_attestation":
            text(evidence.get("statement"), "evidence.statement")
        elif not asset_ids:
            raise ApplicationError("VALIDATION", "Receipt evidence needs an asset")
        if "statement" in evidence:
            text(evidence["statement"], "statement")
        evidence["asset_ids"] = asset_ids
        for identifier in asset_ids:
            self._asset(identifier, "evidence")
        fields = dict(
            opportunity_id=opportunity["id"],
            preparation_id=preparation_id,
            job_version_id=p["job_version_id"],
            resume_version_id=p.get("resume_version_id"),
            channel=text(p.get("channel"), "channel"),
            outcome=outcome,
            submitted_at=submitted_at,
            evidence_json=json_text(evidence),
        )
        if old:
            identifier = old["id"]
            reason = text(p.get("reason"), "reason")
            self._update("applications", identifier, expected, **fields)
        else:
            identifier = new_id()
            now = utc_now()
            reason = p.get("reason") or "User recorded actual outcome"
            self._insert(
                "applications", id=identifier, **fields, created_at=now, updated_at=now
            )
        application = self._row("applications", identifier)
        self._insert(
            "application_events",
            id=new_id(),
            application_id=identifier,
            revision=application["revision"],
            snapshot_json=json_text(
                {
                    "schema_version": 1,
                    "application": application,
                    "preparation": preparation,
                }
            ),
            reason=reason,
            recorded_at=utc_now(),
        )
        status = (
            "applied"
            if outcome == "submitted"
            and opportunity["status"] in {"saved", "deferred", "applying"}
            else opportunity["status"]
        )
        self._update(
            "opportunities", opportunity["id"], opportunity["revision"], status=status
        )
        return self.get_application(identifier)

    def get_material_version(self, identifier):
        row = self._row("material_versions", identifier)
        row["fact_snapshot"] = json.loads(row.pop("fact_snapshot_json"))
        return row

    def get_opportunity(self, identifier):
        row = self._row("opportunities", identifier)
        row["job_ids"] = [
            r[0]
            for r in self.connection.execute(
                "SELECT job_id FROM opportunity_jobs WHERE opportunity_id=? ORDER BY created_at,job_id",
                (identifier,),
            )
        ]
        return row

    def get_preparation(self, identifier):
        row = self._row("application_preparations", identifier)
        row["cooldown_snapshot"] = json.loads(row.pop("cooldown_snapshot_json"))
        if not self._has_job_link(row["job_version_id"], row["opportunity_id"]):
            step = "relink_job"
        elif row["status"] == "deferred":
            step = "deferred"
        elif row["material_confirmed_at"] is None:
            step = "materials"
        elif (
            row["cooldown_status"] == "present" and row["cooldown_confirmed_at"] is None
        ):
            step = "cooldown"
        else:
            step = "manual_apply"
        row["next_step"] = step
        return row

    def get_application(self, identifier):
        row = self._row("applications", identifier)
        row["evidence"] = json.loads(row.pop("evidence_json"))
        row["events"] = []
        for event in self.connection.execute(
            "SELECT * FROM application_events WHERE application_id=? ORDER BY revision",
            (identifier,),
        ):
            item = dict(event)
            item["snapshot"] = json.loads(item.pop("snapshot_json"))
            row["events"].append(item)
        return row
