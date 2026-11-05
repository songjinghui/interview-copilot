"""Explicit paths only: the maintenance CLI never selects a user's live store."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.test_storage import feature, legacy


class MaintenanceCliTest(unittest.TestCase):
    def setUp(self):
        feature(self, "interview_copilot.__main__")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def run_cli(self, *args):
        env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "interview_copilot", *map(str, args)],
            cwd=self.directory,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )

    def test_init_requires_explicit_new_path_and_rejects_reuse(self):
        result = self.run_cli("init-db")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.directory.iterdir()), [])
        path = self.directory / "isolated.sqlite"
        result = self.run_cli("init-db", "--path", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema_version"], 1)
        before = path.read_bytes()
        self.assertNotEqual(self.run_cli("init-db", "--path", path).returncode, 0)
        self.assertEqual(path.read_bytes(), before)

    def test_migrate_outputs_bundle_report_without_switching_source(self):
        source = self.directory / "old.sqlite"
        legacy(source)
        before = source.read_bytes()
        output = self.directory / "bundle"
        result = self.run_cli("migrate-legacy", "--source", source, "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["jobs"], 1)
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue((output / "app.sqlite").exists())

    def test_invalid_database_reports_safe_error_and_no_published_bundle(self):
        source = self.directory / "bad.sqlite"
        source.write_bytes(b"not a sqlite database")
        result = self.run_cli(
            "migrate-legacy", "--source", source, "--output", self.directory / "bundle"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.directory / "bundle").exists())


if __name__ == "__main__":
    unittest.main()
