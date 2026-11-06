"""Build-package smoke: installed outside the repo, isolated runtime, restart auth.

Run after `npm ci --include=dev` and `npm run build` in frontend.
All data and the installed wheel are confined to a TemporaryDirectory.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def run(*args, cwd, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=90)
    if result.returncode:
        diagnostic = (result.stdout + result.stderr).decode("utf-8", errors="replace")[
            -3000:
        ]
        diagnostic = re.sub(
            r"https?://[^\s/@]+:[^\s/@]+@", "https://[redacted]@", diagnostic
        )
        raise RuntimeError(f"Isolated command failed: {args[1:3]}\n{diagnostic}")
    return result


def verify():
    repository = Path(__file__).resolve().parents[1]
    if not (repository / "src/interview_copilot/web/index.html").is_file():
        raise RuntimeError("Build frontend before package verification")
    with tempfile.TemporaryDirectory(prefix="interview-runtime-verify-") as scratch:
        root = Path(scratch).resolve()
        package = root / "package"
        package.mkdir()
        shutil.copy2(repository / "pyproject.toml", package / "pyproject.toml")
        shutil.copytree(
            repository / "src",
            package / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
        )
        wheels, installed = root / "wheels", root / "installed"
        run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-w",
            str(wheels),
            str(package),
            cwd=root,
        )
        wheel = next(wheels.glob("*.whl"))
        run(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(installed),
            str(wheel),
            cwd=root,
        )
        env = {**os.environ, "PYTHONPATH": str(installed)}
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        data = root / "isolated-data"

        def request(path, body=None, token=None):
            headers = {"Origin": origin}
            if token:
                headers["Authorization"] = "Bearer " + token
            if body is not None:
                headers["Content-Type"] = "application/json"
            with urlopen(
                Request(
                    origin + path,
                    headers=headers,
                    data=json.dumps(body).encode() if body is not None else None,
                ),
                timeout=5,
            ) as response:
                return response.read(), response.headers

        def start():
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "interview_copilot",
                    "serve",
                    "--data-dir",
                    str(data),
                    "--port",
                    str(port),
                    "--no-browser",
                ],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Installed service exited before readiness")
                    try:
                        request("/health")
                        return process
                    except OSError:
                        time.sleep(0.05)
                raise RuntimeError("Installed service did not become ready")
            except BaseException:
                process.kill()
                process.communicate()
                raise

        def stop(process):
            process.kill()  # deliberate crash of this isolated child only
            out, error = process.communicate(timeout=10)
            return out + error

        process = start()
        token = None
        try:
            index, headers = request("/")
            assert "求职助手" in index.decode()
            assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
            assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.decode())
            assert len(assets) >= 2
            for asset in assets:
                assert len(request(asset)[0]) > 100
            try:
                request("/api/v1/profile")
                raise AssertionError("Unauthenticated query succeeded")
            except HTTPError as error:
                assert error.code == 401
            # Resolve the installed module and use the actual authenticated IPC.
            bootstrap_script = "from pathlib import Path; from interview_copilot.launcher import request_open; from interview_copilot.session import load_key; import sys; p=Path(sys.argv[1]); print(request_open(p,load_key(p/'session.key')))"
            url = (
                run(
                    sys.executable, "-c", bootstrap_script, str(data), cwd=root, env=env
                )
                .stdout.decode()
                .strip()
            )
            nonce = url.split("#bootstrap=", 1)[1]
            exchange = json.loads(request("/session/exchange", {"nonce": nonce})[0])
            token = exchange["token"]
            envelope = {
                "request_id": str(uuid4()),
                "command": "ImportMaterial",
                "input": {
                    "label": "Runtime synthetic resume",
                    "text": "Synthetic verification only",
                },
            }
            saved = json.loads(request("/api/v1/commands", envelope, token)[0])
            log = stop(process)
            process = None
            assert token.encode() not in log and nonce.encode() not in log
            process = start()
            replay = json.loads(request("/api/v1/commands", envelope, token)[0])
            assert saved == replay
            profile = json.loads(request("/api/v1/profile", token=token)[0])
            assert len(profile["materials"]) == 1
            assert (
                json.loads(request("/session/renew", {}, token)[0])["workspace"]
                == exchange["workspace"]
            )
            # The authenticated CLI does not emit paths, tokens or input text in logs.
            print(
                json.dumps(
                    {
                        "result": "passed",
                        "installed_outside_repository": True,
                        "assets_served": len(assets),
                        "crash_restart_session_and_receipt": True,
                        "persistent_materials": 1,
                    }
                )
            )
        finally:
            if process is not None:
                stop(process)


if __name__ == "__main__":
    verify()
