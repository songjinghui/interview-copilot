"""Authenticated loopback HTTP adapter; all writes use domain commands."""

from __future__ import annotations
import json
import hmac
import hashlib
from pathlib import Path
import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from .application import ApplicationError
from .session import Sessions
from .storage import Database, SchemaError
from .workbench import WorkbenchService

MAX_JSON = 1024 * 1024
ERROR_STATUS = {
    "UNKNOWN_COMMAND": 400,
    "NOT_FOUND": 404,
    "SOURCE_UNAVAILABLE": 403,
    "REVISION_CONFLICT": 409,
    "REQUEST_ID_REUSED": 409,
    "INVALID_STATE": 409,
    "STORAGE_CONSTRAINT": 409,
    "BUSY": 503,
    "STORAGE_ERROR": 503,
}


def failure(code, message, status, *, request_id=None, details=None, retryable=False):
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            },
            "request_id": request_id,
        },
        status_code=status,
    )


class Boundary:
    """Validate before routing and cap streamed bodies, not just Content-Length."""

    def __init__(self, app, *, sessions, port):
        self.app, self.sessions = app, sessions
        self.host = f"127.0.0.1:{port}"
        self.origin = "http://" + self.host

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {}
        duplicate = False
        for key, value in scope["headers"]:
            if (
                key in {b"host", b"origin", b"authorization", b"content-length"}
                and key in headers
            ):
                duplicate = True
            headers[key] = value.decode("latin-1")

        async def safe_send(message):
            if message["type"] == "http.response.start":
                message["headers"] += [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (
                        b"content-security-policy",
                        b"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                    ),
                ]
            await send(message)

        async def reject(code, message, status):
            await failure(code, message, status)(scope, receive, safe_send)

        if duplicate or headers.get(b"host") != self.host:
            return await reject("HOST_REJECTED", "Invalid local service host", 403)
        write = scope["method"] not in {"GET", "HEAD"}
        if write and headers.get(b"origin") != self.origin:
            return await reject(
                "ORIGIN_REJECTED", "Open the workbench from the local launcher", 403
            )
        path = scope["path"]
        if path.startswith("/api/") or path == "/session/renew":
            try:
                authorization = headers.get(b"authorization", "")
                if not authorization.startswith("Bearer "):
                    raise ValueError()
                self.sessions.verify(authorization[7:])
            except ValueError:
                return await reject(
                    "SESSION_REQUIRED", "请重新打开求职助手以恢复会话", 401
                )
        if write:
            if (
                headers.get(b"content-type", "").split(";")[0].strip()
                != "application/json"
            ):
                return await reject("CONTENT_TYPE", "JSON content is required", 415)
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_JSON:
                    return await reject("TOO_LARGE", "Text input exceeds 1 MiB", 413)
                if not message.get("more_body", False):
                    break
            sent = False

            async def bounded_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await receive()

            return await self.app(scope, bounded_receive, safe_send)
        return await self.app(scope, receive, safe_send)


async def body_object(request):
    def invalid(_):
        raise ValueError()

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    try:
        body = json.loads(
            await request.body(), parse_constant=invalid, object_pairs_hook=unique
        )
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (ValueError, UnicodeError, RecursionError):
        raise ApplicationError("BAD_REQUEST", "Invalid JSON object") from None


def create_app(database_path: Path, sessions: Sessions, *, port=17863, static_dir=None):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Invalid local service port")
    database_path = Path(database_path)
    with Database(database_path):
        pass
    static = (
        Path(static_dir) if static_dir else Path(__file__).parent / "web"
    ).resolve()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(Boundary, sessions=sessions, port=port)
    workspace = hmac.new(
        sessions.key, b"public-workspace-identity", hashlib.sha256
    ).hexdigest()

    @app.exception_handler(ApplicationError)
    async def application_error(request, error):
        return failure(
            error.code,
            str(error),
            400 if error.code == "BAD_REQUEST" else ERROR_STATUS.get(error.code, 422),
            request_id=getattr(request.state, "request_id", None),
            details=error.details,
            retryable=error.retryable,
        )

    def database_call(operation):
        try:
            with Database(database_path) as database:
                return operation(WorkbenchService(database))
        except ApplicationError:
            raise
        except (sqlite3.Error, OSError, SchemaError):
            raise ApplicationError(
                "STORAGE_ERROR", "本地资料暂不可用，请重试", retryable=True
            ) from None

    @app.get("/health")
    async def health():
        return {"service": "interview-copilot", "api_version": 1, "state": "ready"}

    @app.post("/session/exchange")
    async def exchange(request: Request):
        body = await body_object(request)
        if set(body) != {"nonce"}:
            raise ApplicationError("BAD_REQUEST", "Bootstrap nonce is required")
        try:
            return {"token": sessions.exchange(body["nonce"]), "workspace": workspace}
        except ValueError:
            return failure(
                "SESSION_REQUIRED", "启动凭据已过期，请重新打开求职助手", 401
            )

    @app.post("/session/renew")
    async def renew(request: Request):
        return {
            "token": sessions.renew(request.headers["authorization"][7:]),
            "workspace": workspace,
        }

    @app.post("/api/v1/commands")
    async def command(request: Request):
        body = await body_object(request)
        if (
            set(body) - {"request_id", "command", "input", "expected_revision"}
            or not {"request_id", "command", "input"} <= set(body)
            or not isinstance(body["request_id"], str)
            or not isinstance(body["input"], dict)
        ):
            raise ApplicationError("BAD_REQUEST", "Invalid command envelope")
        request.state.request_id = body["request_id"][:64]
        return await run_in_threadpool(
            database_call,
            lambda service: service.execute(
                body["request_id"],
                body["command"],
                body["input"],
                expected_revision=body.get("expected_revision"),
            ),
        )

    @app.get("/api/v1/{path:path}")
    async def query(path: str, request: Request):
        def read(service):
            service.connection.execute("BEGIN")
            try:
                return service.query(path, dict(request.query_params))
            finally:
                service.connection.rollback()

        return await run_in_threadpool(database_call, read)

    @app.get("/{path:path}")
    async def page(path: str):
        candidate = (static / (path or "index.html")).resolve()
        if not candidate.is_relative_to(static) or not candidate.is_file():
            return failure("NOT_FOUND", "页面尚未构建或文件不存在", 404)
        return FileResponse(candidate)

    return app
