from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TicketCategory = Literal["técnica", "comercial", "financeira", "escalação"]
# 1 = mais urgente, 4 = menos urgente (alinhado ao prompt do classificador)
Urgency = Literal[1, 2, 3, 4]

ALLOWED_CATEGORIES: frozenset[str] = frozenset({"técnica", "comercial", "financeira", "escalação"})


@dataclass(frozen=True)
class TriageResult:
    category: TicketCategory
    urgency: Urgency
    customer_id: str
    customer_name: str
    confidence: float
    rationale: str

