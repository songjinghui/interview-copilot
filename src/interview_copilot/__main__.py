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
    args = parser.parse_args(argv)
    try:
        if args.command == "init-db":
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
        print(
            json.dumps(
                {
                    "error": "STORAGE_OPERATION_FAILED",
                    "message": "Check the explicit source and destination paths and schema; no source data was replaced.",
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
