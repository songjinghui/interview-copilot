"""Maintenance commands for explicitly named, isolated storage paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .storage import Database, SchemaError
from .storage.legacy import migrate_legacy


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser(
        "init-db", help="Create a new database; existing paths are refused"
    )
    initialize.add_argument("--path", type=Path, required=True)
    migrate = commands.add_parser(
        "migrate-legacy",
        help="Copy the legacy store into a new bundle; leave the source selected and unchanged",
    )
    migrate.add_argument("--source", type=Path, required=True)
    migrate.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser(
        "serve",
        help="Run the authenticated local workbench with an explicit data directory",
    )
    serve.add_argument("--data-dir", type=Path, required=True)
    serve.add_argument("--port", type=int, default=17863)
    serve.add_argument("--no-browser", action="store_true")
    opener = commands.add_parser(
        "open", help="Open an already running workbench through authenticated user IPC"
    )
    opener.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"serve", "open"}:
            from . import launcher

            if args.command == "serve":
                launcher.serve(
                    args.data_dir, port=args.port, open_browser=not args.no_browser
                )
            else:
                launcher.open_workbench(args.data_dir)
            return 0
        elif args.command == "init-db":
            args.path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents overwriting a path that appears after
            # validation. A failed initialization may leave an empty reserved file.
            with args.path.open("xb"):
                pass
            with Database(args.path):
                result = {"schema_version": 1, "path": str(args.path.resolve())}
        else:
            result = migrate_legacy(args.source, args.output)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, SchemaError, sqlite3.Error):
        local_service = args.command in {"serve", "open"}
        print(
            json.dumps(
                {
                    "error": (
                        "LOCAL_SERVICE_FAILED"
                        if local_service
                        else "STORAGE_OPERATION_FAILED"
                    ),
                    "message": (
                        "Build the frontend, start serve with this --data-dir and a free local port, then use open with the same --data-dir. An existing service or invalid key is never replaced."
                        if local_service
                        else "Check the explicit source and destination paths and schema; no source data was replaced."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
