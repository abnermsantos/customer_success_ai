from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TicketCategory = Literal["técnica", "comercial", "financeira", "escalação"]
Urgency = Literal["baixo", "médio", "alto", "crítico"]


@dataclass(frozen=True)
class TriageResult:
    category: TicketCategory
    urgency: Urgency
    customer_id: str
    customer_name: str
    confidence: float
    rationale: str

