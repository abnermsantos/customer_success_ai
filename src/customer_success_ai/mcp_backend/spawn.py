"""Autostart do servidor MCP (streamable HTTP) em modo local."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from customer_success_ai.observability import mcp_server_log_path

_HEALTH_POLL_S = 0.25
_HEALTH_TIMEOUT_S = 60.0


def should_autostart_mcp(mcp_url: str) -> bool:
    if os.getenv("MCP_AUTOSTART", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    u = urlparse(mcp_url.strip())
    host = (u.hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _parse_mcp_url(mcp_url: str) -> tuple[str, int, str]:
    u = urlparse(mcp_url.strip())
    if not u.hostname:
        raise ValueError(f"MCP_URL inválida (sem host): {mcp_url!r}")
    host = u.hostname
    port = u.port
    if port is None:
        port = 443 if (u.scheme or "").lower() == "https" else 80
    path = u.path or "/mcp"
    return host, port, path


def _wait_for_mcp(mcp_url: str, *, timeout_s: float = _HEALTH_TIMEOUT_S) -> None:
    """
    Heurística simples de readiness:
    - Faz GET no endpoint /mcp com Accept: application/json.
    - Considera "healthy" se não for 404/connection error.
    """
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(mcp_url, headers={"Accept": "application/json"}, timeout=3.0, follow_redirects=True)
            # 405/406 são respostas aceitáveis para método/headers,
            # o importante é o endpoint existir e estar respondendo.
            if r.status_code not in (404,):
                return
        except Exception as e:
            last_err = e
        time.sleep(_HEALTH_POLL_S)
    raise RuntimeError(f"Timeout ao aguardar MCP em {mcp_url!r}" + (f": {last_err}" if last_err else "")) from last_err


def start_local_mcp_server(*, tickets_api_url: str, mcp_url: str) -> subprocess.Popen[bytes]:
    cmd = [sys.executable, "-m", "customer_success_ai.cli", "mcp"]
    env = os.environ.copy()
    env["TICKETS_API_URL"] = tickets_api_url
    env["MCP_URL"] = mcp_url
    env["MCP_QUIET_LAUNCHER"] = "1"

    log_path = mcp_server_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        cmd,
        cwd=PathCwd.repo_root(),
        env=env,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=False,
    )
    # Mantém FD aberto enquanto o filho existe; evita traceback no GC ao fechar cedo demais.
    setattr(proc, "_mcp_stdout_fp", log_fp)
    return proc


def stop_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


class PathCwd:
    @staticmethod
    def repo_root() -> str:
        # `customer_success_ai.cli` é resolvido via package install, mas queremos
        # rodar do repo quando usado em dev. Usar cwd atual como fallback.
        here = Path(__file__).resolve()
        # src/customer_success_ai/mcp_backend/spawn.py -> repo root é 4 níveis acima
        # (customer_success_ai -> src -> repo)
        try:
            return str(here.parents[3])
        except Exception:
            return os.getcwd()


@contextlib.contextmanager
def local_mcp_session(*, tickets_api_url: str, mcp_url: str):
    proc: subprocess.Popen[bytes] | None = None
    if should_autostart_mcp(mcp_url):
        proc = start_local_mcp_server(tickets_api_url=tickets_api_url, mcp_url=mcp_url)
        try:
            _wait_for_mcp(mcp_url)
        except Exception:
            if proc is not None:
                stop_process(proc)
            raise
        log_path = mcp_server_log_path()
        print(f"Serving MCP backend via uvicorn: {mcp_url} (log em {log_path})")
    try:
        yield proc
    finally:
        if proc is not None:
            stop_process(proc)

