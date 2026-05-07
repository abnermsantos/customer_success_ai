from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from customer_success_ai.workflow.state import WorkflowState


@dataclass(frozen=True)
class PersistedRun:
    run_id: str
    created_at_utc: str
    state: dict[str, Any]


class RunStorage(Protocol):
    def init(self) -> None:
        """Inicializa o storage (ex.: cria tabelas/migrações)."""

    def save_run(self, *, run_id: str, created_at_utc: str, state: WorkflowState) -> None:
        """Persiste uma execução completa do workflow."""

    def get_run(self, run_id: str) -> PersistedRun | None:
        """Carrega uma execução por id."""

