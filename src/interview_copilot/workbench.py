"""Manual imports and public read views for the local workbench."""

from __future__ import annotations

import base64
import json
from .application import (
    ApplicationService,
    ApplicationError,
    public_url,
    structured,
    text,
)
from .jobs.model import JobRecord
from .jobs.store import SqliteJobStore
from .storage.database import new_id, utc_now, digest, json_text


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
        result["feedback"], result["interviews"] = [], []
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
        }:
            return {
                "jobs": self.job_detail,
                "opportunities": self.opportunity_detail,
                "preparations": self.preparation_detail,
                "applications": self.get_application,
            }[parts[0]](parts[1])
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
