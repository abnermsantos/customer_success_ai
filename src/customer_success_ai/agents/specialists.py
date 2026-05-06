from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from langchain_openai import ChatOpenAI

from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.triage.models import TicketCategory, TriageResult
from customer_success_ai.workflow.state import Ticket


@dataclass(frozen=True)
class SpecialistOutput:
    draft: str
    confidence: float
    requires_human_review: bool
    rationale: str


def _format_citations(citations: list[dict[str, Any]]) -> str:
    lines = []
    for c in citations:
        src = c.get("source")
        ref = c.get("ref")
        path = c.get("path")
        snippet = (c.get("snippet") or "").strip().replace("\n", " ")
        lines.append(f"- [{src}] {ref}" + (f" ({path})" if path else "") + f": {snippet[:180]}")
    return "\n".join(lines)


def _specialist_system(category: TicketCategory) -> str:
    return f"""Você é um agente especialista de Customer Success na categoria: {category}.
Você vai gerar uma resposta para o analista (não enviar ao cliente diretamente).

Regras:
- Seja objetivo, orientado a ação.
- Use APENAS as fontes fornecidas nas citações para afirmar fatos.
- Se faltar evidência nas fontes, peça ao analista os dados necessários (ex.: print do erro, linhas do extrato).
- Retorne SOMENTE JSON válido com chaves:
  draft (string), confidence (float 0..1), requires_human_review (bool), rationale (string curta).
"""


def run_specialist(
    ticket: Ticket,
    *,
    triage: TriageResult,
    citations: list[dict[str, Any]],
    is_sensitive: bool,
    logger: JsonlLogger,
    model: str = "gpt-4o-mini",
) -> SpecialistOutput:
    with StepTimer(logger, f"worker_{triage.category}"):
        llm = ChatOpenAI(model=model, temperature=0)

        payload = {
            "ticket": {
                "id": ticket["id"],
                "titulo": ticket["titulo"],
                "descricao": ticket["descricao"],
                "tipo": ticket["tipo"],
                "prioridade": ticket["prioridade"],
                "status": ticket["status"],
                "id_cliente": ticket["id_cliente"],
                "nome_cliente": ticket["nome_cliente"],
            },
            "triage": asdict(triage),
            "citations": citations,
            "is_sensitive": is_sensitive,
        }

        raw = llm.invoke(
            [
                {"role": "system", "content": _specialist_system(triage.category)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        ).content

        data = json.loads(raw)
        out = SpecialistOutput(
            draft=str(data["draft"]),
            confidence=float(data["confidence"]),
            requires_human_review=bool(data["requires_human_review"]),
            rationale=str(data["rationale"]),
        )
        logger.log(
            "specialist_result",
            category=triage.category,
            confidence=out.confidence,
            requires_human_review=out.requires_human_review,
        )
        return out

