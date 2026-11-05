"""Isolated real HTTP fixture for DOM integration tests; never the user's data."""

from pathlib import Path
import json
import secrets
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from interview_copilot.http import create_app
from interview_copilot.launcher import reserve_port
from interview_copilot.session import Sessions
import uvicorn

with tempfile.TemporaryDirectory(prefix="interview-ui-test-") as directory:
    with reserve_port(0) as sock:
        port = sock.getsockname()[1]
        sessions = Sessions(secrets.token_bytes(32))
        app = create_app(Path(directory) / "app.sqlite", sessions, port=port)
        server = uvicorn.Server(
            uvicorn.Config(app, access_log=False, log_level="error")
        )
        thread = threading.Thread(
            target=lambda: server.run(sockets=[sock]), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Fixture did not start")
            time.sleep(0.02)
        print(
            json.dumps(
                {"origin": f"http://127.0.0.1:{port}", "nonce": sessions.bootstrap()}
            ),
            flush=True,
        )
        sys.stdin.readline()
        server.should_exit = True
        thread.join(10)
        if thread.is_alive():
            raise RuntimeError("Fixture did not stop")
