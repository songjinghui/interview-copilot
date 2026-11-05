"""One-use local bootstrap, signed sessions, and current-user DPAPI secrets."""

from __future__ import annotations
import base64
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time


class Sessions:
    def __init__(self, key: bytes, *, clock=time.time):
        if len(key) < 32:
            raise ValueError("Session key is too short")
        self.key, self.clock = key, clock
        self.nonces = {}
        self.lock = threading.Lock()

    def bootstrap(self):
        with self.lock:
            self.nonces = {
                n: expiry for n, expiry in self.nonces.items() if expiry > self.clock()
            }
            nonce = secrets.token_urlsafe(32)
            self.nonces[nonce] = self.clock() + 60
            return nonce

    def _token(self):
        payload = base64.urlsafe_b64encode(
            json.dumps(
                {"expires": self.clock() + 8 * 3600, "id": secrets.token_hex(16)},
                separators=(",", ":"),
            ).encode()
        ).decode()
        return (
            payload
            + "."
            + hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
        )

    def exchange(self, nonce):
        with self.lock:
            if not isinstance(nonce, str) or self.nonces.pop(nonce, 0) <= self.clock():
                raise ValueError("Bootstrap expired or already used")
        return self._token()

    def verify(self, token):
        try:
            payload, signature = token.split(".")
            expected = hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(payload))
            if data["expires"] <= self.clock():
                raise ValueError()
            return True
        except (TypeError, ValueError, AttributeError, KeyError):
            raise ValueError("Session expired or invalid") from None

    def renew(self, token):
        self.verify(token)
        return self._token()


def _protect(data: bytes, *, decrypt=False):
    if os.name != "nt":
        raise OSError("The packaged launcher requires Windows current-user DPAPI")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.DWORD),
            ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [
        ctypes.c_void_p
    ], ctypes.c_void_p
    # UI_FORBIDDEN only; deliberately no LOCAL_MACHINE scope.
    if not function(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)
    ):
        raise OSError(
            "User credential store could not protect/unprotect the session key"
        )
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        kernel.LocalFree(result.data)


def load_key(path: Path):
    if path.exists():
        key = _protect(path.read_bytes(), decrypt=True)
        if len(key) != 32:
            raise OSError("Invalid persisted session key")
        return key
    key = secrets.token_bytes(32)
    protected = _protect(key)
    # Caller holds the data-directory instance lock; never overwrite a key.
    with path.open("xb") as file:
        file.write(protected)
        file.flush()
        os.fsync(file.fileno())
    return key
