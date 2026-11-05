"""Explicit-directory Windows launcher, exclusive loopback port and user IPC."""

from __future__ import annotations
from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import socket
import threading
import webbrowser
from multiprocessing.connection import (
    Listener,
    Client,
    deliver_challenge,
    answer_challenge,
)
from multiprocessing import AuthenticationError
from .session import Sessions, load_key


class InstanceLock:
    """OS byte-range lock: released on crash; never delete a live lock file."""

    def __init__(self, directory):
        self.path = Path(directory) / "service.lock"
        self.file = None

    def __enter__(self):
        if os.name != "nt":
            raise OSError("This launcher requires Windows")
        import msvcrt

        self.file = self.path.open("a+b")
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            self.file = None
            raise OSError("This data directory already has a running service") from None
        return self

    def __exit__(self, *args):
        if self.file is not None:
            import msvcrt

            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


@contextmanager
def reserve_port(port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        server.bind(("127.0.0.1", port))
        server.listen(128)
        yield server
    finally:
        server.close()


def pipe_name(directory):
    identity = os.path.normcase(str(Path(directory).resolve()))
    return (
        r"\\.\pipe\interview-copilot-" + hashlib.sha256(identity.encode()).hexdigest()
    )


def ipc_key(key):
    return hmac.new(key, b"interview-copilot-local-ipc-v1", hashlib.sha256).digest()


class BootstrapPipe:
    def __init__(self, directory, sessions, port):
        self.address, self.sessions, self.port = pipe_name(directory), sessions, port
        self.stopping = threading.Event()

    def __enter__(self):
        self.listener = Listener(self.address, family="AF_PIPE")
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return self

    def _serve(self):
        while not self.stopping.is_set():
            try:
                connection = self.listener.accept()
            except OSError:
                return
            with connection:
                if self.stopping.is_set():
                    return
                timer = threading.Timer(5, connection.close)
                timer.daemon = True
                timer.start()
                try:
                    key = ipc_key(self.sessions.key)
                    deliver_challenge(connection, key)
                    answer_challenge(connection, key)
                    # Never deserialize pickle or accept a filesystem path/action.
                    if connection.recv_bytes(16) == b"open":
                        url = f"http://127.0.0.1:{self.port}/#bootstrap={self.sessions.bootstrap()}"
                        connection.send_bytes(url.encode())
                except (OSError, EOFError, ValueError, AuthenticationError):
                    pass
                finally:
                    timer.cancel()

    def __exit__(self, *args):
        self.stopping.set()
        try:
            with Client(self.address, family="AF_PIPE"):
                pass
        except OSError:
            pass
        self.thread.join(6)
        self.listener.close()


def request_open(directory, key):
    with Client(pipe_name(directory), family="AF_PIPE") as connection:
        timer = threading.Timer(5, connection.close)
        timer.daemon = True
        timer.start()
        try:
            answer_challenge(connection, ipc_key(key))
            deliver_challenge(connection, ipc_key(key))
            connection.send_bytes(b"open")
            return connection.recv_bytes(512).decode()
        finally:
            timer.cancel()


def open_workbench(directory):
    directory = Path(directory).resolve()
    key_path = directory / "session.key"
    if not key_path.is_file():
        raise OSError("Start the service with this data directory first")
    url = request_open(directory, load_key(key_path))
    webbrowser.open(url)


def serve(directory, *, port=17863, open_browser=True, static_dir=None):
    import uvicorn
    from .http import create_app

    directory = Path(directory).resolve()
    static = Path(static_dir) if static_dir else Path(__file__).parent / "web"
    if not (static / "index.html").is_file():
        raise OSError("Build the workbench first: cd frontend; npm ci; npm run build")
    if not 1024 <= port <= 65535:
        raise OSError("Choose a port between 1024 and 65535")
    directory.mkdir(parents=True, exist_ok=True)
    with InstanceLock(directory), reserve_port(port) as server:
        sessions = Sessions(load_key(directory / "session.key"))
        app = create_app(
            directory / "app.sqlite", sessions, port=port, static_dir=static
        )
        with BootstrapPipe(directory, sessions, port):
            if open_browser:
                # The socket is already reserved; exchange waits until ASGI is ready.
                open_workbench(directory)
            config = uvicorn.Config(
                app, host="127.0.0.1", port=port, access_log=False, log_level="warning"
            )
            uvicorn.Server(config).run(sockets=[server])
