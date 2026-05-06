"""Sobe o app_mock via uvicorn quando TICKETS_API_URL aponta para este host."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_HEALTH_POLL_S = 0.25
_HEALTH_TIMEOUT_S = 60.0


def src_directory() -> Path:
    """src/ — uvicorn resolve `app_mock` quando cwd é este diretório."""
    return Path(__file__).resolve().parents[2]


def should_autostart_mock(api_base: str) -> bool:
    if os.getenv("TICKETS_MOCK_AUTOSTART", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    parsed = urlparse(normalize_base_for_parse(api_base))
    host = (parsed.hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def normalize_base_for_parse(base: str) -> str:
    """Garante netloc parseável quando o usuário informa só path (evitar edge cases)."""
    b = base.strip().rstrip("/")
    if b.startswith(("http://", "https://")):
        return b
    return f"http://{b}"


def _parse_bind_target(api_base: str) -> tuple[str, int]:
    u = urlparse(normalize_base_for_parse(api_base))
    if not u.hostname:
        raise ValueError(f"TICKETS_API_URL inválida (sem host): {api_base!r}")
    host = u.hostname
    port = u.port
    if port is None:
        port = 443 if u.scheme == "https" else 80
    return host, port


def wait_for_health(health_endpoint: str, *, timeout_s: float = _HEALTH_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            req = Request(health_endpoint, headers={"Accept": "application/json"}, method="GET")
            with urlopen(req, timeout=5.0) as resp:
                if 200 <= resp.status < 300:
                    return
        except (OSError, URLError, TimeoutError) as e:
            last_err = e
        time.sleep(_HEALTH_POLL_S)
    raise RuntimeError(
        f"Timeout ao aguardar API de tickets em {health_endpoint!r}"
        + (f": {last_err}" if last_err else "")
    ) from last_err


def start_local_mock_server(api_base: str) -> subprocess.Popen[bytes]:
    host, port = _parse_bind_target(api_base)
    src_root = src_directory()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app_mock.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    env = os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        cwd=src_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=None,
        stdin=subprocess.DEVNULL,
    )
    return proc


def stop_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


@contextlib.contextmanager
def local_tickets_mock_session(api_base: str, health_endpoint: str):
    proc: subprocess.Popen[bytes] | None = None
    if should_autostart_mock(api_base):
        proc = start_local_mock_server(api_base)
        try:
            wait_for_health(health_endpoint)
        except Exception:
            if proc is not None:
                stop_process(proc)
            raise
        print(f"Serving tickets mock via uvicorn (host conforme TICKETS_API_URL): {health_endpoint}")
    try:
        yield proc
    finally:
        if proc is not None:
            stop_process(proc)
