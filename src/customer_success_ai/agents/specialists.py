from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from langchain_openai import ChatOpenAI

from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.triage.models import TicketCategory, TriageResult
from customer_success_ai.workflow.state import Ticket


def _extract_json(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        return fence.group(1).strip()
    return text


def _msg_content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


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
- Use APENAS as fontes fornecidas nas citações e/ou no customer_context (CRM) para afirmar fatos.
- Se faltar evidência nas fontes, peça ao analista os dados necessários (ex.: print do erro, linhas do extrato).
- Retorne SOMENTE JSON válido com chaves:
  draft (string), confidence (float 0..1), requires_human_review (bool), rationale (string curta).
"""

def run_specialist(
    ticket: Ticket,
    *,
    triage: TriageResult,
    citations: list[dict[str, Any]],
    customer_context: dict[str, Any] | None,
    as_of_utc: str | None,
    is_sensitive: bool,
    logger: JsonlLogger,
    model: str = "gpt-4o-mini",
    feedback_memory: list[dict[str, Any]] | None = None,
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
            "customer_context": customer_context,
            "as_of_utc": as_of_utc,
            "is_sensitive": is_sensitive,
            "feedback_memory": feedback_memory or [],
        }

        msg = llm.invoke(
            [
                {"role": "system", "content": _specialist_system(triage.category)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        raw = _msg_content_to_str(getattr(msg, "content", None))

        try:
            data = json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            logger.log(
                "specialist_failed",
                category=triage.category,
                reason="invalid_json_response",
                error=str(e),
                raw_preview=raw[:800] if raw else "",
            )
            return SpecialistOutput(
                draft=(
                    "O modelo especialista não retornou um JSON válido. "
                    "Redija a resposta manualmente usando as citações acima "
                    "(erro técnico: resposta não parseável)."
                ),
                confidence=0.0,
                requires_human_review=True,
                rationale=f"Falha ao interpretar JSON do especialista: {e}",
            )

        try:
            out = SpecialistOutput(
                draft=str(data["draft"]),
                confidence=float(data["confidence"]),
                requires_human_review=bool(data["requires_human_review"]),
                rationale=str(data["rationale"]),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.log(
                "specialist_failed",
                category=triage.category,
                reason="invalid_payload_shape",
                error=str(e),
                raw_preview=raw[:800] if raw else "",
            )
            return SpecialistOutput(
                draft=(
                    "O modelo retornou JSON com formato inesperado. "
                    "Redija a resposta manualmente com base nas fontes citadas."
                ),
                confidence=0.0,
                requires_human_review=True,
                rationale=f"Campos esperados ausentes ou inválidos no JSON: {e}",
            )

        logger.log(
            "specialist_result",
            category=triage.category,
            confidence=out.confidence,
            requires_human_review=out.requires_human_review,
        )
        return out
