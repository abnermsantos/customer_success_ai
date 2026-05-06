from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    log_dir: Path
    log_level: str
    mocks_dir: Path
    tickets_history_path: Path
    kb_dir: Path

