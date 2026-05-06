from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from customer_success_ai.triage.models import TriageResult


class Ticket(TypedDict):
    id: str
    titulo: str
    descricao: str
    tipo: str
    status: str
    prioridade: str
    responsavel: str
    id_cliente: str
    nome_cliente: str
    criado_em: str
    atualizado_em: str


HILDecision = Literal["aprovar", "rejeitar", "corrigir"]


@dataclass
class WorkflowState:
    ticket: Ticket
    open_tickets_for_customer: int = 0
    is_sensitive: bool = False
    consulted_sources: list[dict[str, Any]] = field(default_factory=list)
    triage: TriageResult | None = None
    classification_error: str | None = None
    draft: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    specialist: str | None = None
    requires_human_review: bool = False
    hil_decision: HILDecision | None = None
    hil_correction: str | None = None

