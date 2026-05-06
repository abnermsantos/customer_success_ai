from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Citation:
    source: str  # "kb" | "tickets"
    ref: str  # e.g. doc_id, ticket_id
    path: str | None
    snippet: str
    metadata: dict[str, Any]

