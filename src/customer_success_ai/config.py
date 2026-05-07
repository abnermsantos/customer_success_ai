from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    log_dir: Path
    log_level: str
    mocks_dir: Path
    runs_db_path: Path
    checkpoints_db_path: Path
    openai_api_key: str | None
    tickets_api_base: str
    tickets_historico_url: str
    tickets_health_url: str
    kb_api_base: str
    kb_search_url: str
    kb_create_url: str
