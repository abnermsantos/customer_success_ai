from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def mcp_server_log_path() -> Path:
    """Arquivo texto para logs do processo MCP (uvicorn / stderr). Igual pasta do JSONL do app."""
    log_dir = Path(os.getenv("LOG_DIR", ".logs"))
    filename = os.getenv("MCP_SERVER_LOG", "mcp-server.log")
    return log_dir / filename


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JsonlLogger:
    path: Path
    thread_id: str

    def log(self, event: str, **fields: Any) -> None:
        payload: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "thread_id": self.thread_id,
            "event": event,
            **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


@dataclass
class StepTimer:
    logger: JsonlLogger
    step: str
    _t0: float = 0.0

    def __enter__(self) -> "StepTimer":
        self._t0 = time.perf_counter()
        self.logger.log("step_start", step=self.step)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed_ms = int((time.perf_counter() - self._t0) * 1000)
        if exc is None:
            self.logger.log("step_end", step=self.step, latency_ms=elapsed_ms)
        else:
            self.logger.log(
                "step_error",
                step=self.step,
                latency_ms=elapsed_ms,
                error_type=getattr(exc_type, "__name__", str(exc_type)),
                error=str(exc),
            )

