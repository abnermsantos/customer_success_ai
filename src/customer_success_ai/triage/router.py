from __future__ import annotations

import json
import re
from dataclasses import asdict

from langchain_openai import ChatOpenAI

from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.triage.models import ALLOWED_CATEGORIES, TriageResult
from customer_success_ai.workflow.state import Ticket


SYSTEM = """Você é um agente classificador de tickets de Customer Success.
Tarefa: dado um ticket em português, classifique e complemente para o painel de atendimento:
- category: uma de ["técnica","comercial","financeira","escalação"]
- urgency: inteiro 1..4 (1=mais urgente, 4=menos urgente)
- confidence: float 0..1
- rationale: 1 frase curta justificando
- titulo: uma linha curta (idealmente até 120 caracteres) que resume o problema para o título do ticket

Se o ticket for ambíguo, incompleto ou não se encaixar claramente em nenhuma categoria acima,
responda com category: null e urgency: null, confidence próximo de 0 e explique em rationale.

Responda SOMENTE em JSON válido com as chaves: category, urgency, confidence, rationale, titulo.
"""

URGENCY_TO_PRIORIDADE = {1: "crítica", 2: "alta", 3: "média", 4: "baixa"}


def _extract_json(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        return fence.group(1).strip()
    return text


def _normalize_category(cat: str) -> str:
    c = cat.strip().lower()
    aliases = {
        "tecnica": "técnica",
        "escalacao": "escalação",
        "financeira": "financeira",
        "comercial": "comercial",
    }
    return aliases.get(c, c)


def _parse_triage_payload(data: dict, ticket: Ticket) -> tuple[TriageResult | None, str | None]:
    cat = data.get("category")
    urg = data.get("urgency")
    rationale = data.get("rationale")

    if cat is None or urg is None:
        return None, str(rationale or "Classificação recusada pelo modelo (category/urgency nulos).")

    if isinstance(cat, str):
        cat = _normalize_category(cat)
    if cat not in ALLOWED_CATEGORIES:
        return None, f"Categoria inválida ou desconhecida pelo sistema: {cat!r}."

    try:
        urg_i = int(urg)
    except (TypeError, ValueError):
        return None, f"urgency inválida: {urg!r}."

    if urg_i not in (1, 2, 3, 4):
        return None, f"urgency fora do intervalo 1..4: {urg_i}."

    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None, "confidence inválido."

    if not (0.0 <= conf <= 1.0):
        return None, f"confidence fora do intervalo 0..1: {conf}."

    raw_titulo = data.get("titulo")
    ticket_titulo: str | None
    if raw_titulo is None:
        ticket_titulo = None
    elif isinstance(raw_titulo, str):
        s = raw_titulo.strip()
        ticket_titulo = (s[:200] + "…") if len(s) > 200 else s if s else None
    else:
        return None, f"titulo inválido (esperado string ou null): {raw_titulo!r}."

    result = TriageResult(
        category=cat,
        urgency=urg_i,  # type: ignore[arg-type]
        customer_id=ticket["id_cliente"],
        customer_name=ticket["nome_cliente"],
        confidence=conf,
        rationale=str(rationale or ""),
        ticket_titulo=ticket_titulo,
    )
    return result, None


def _fallback_titulo_from_descricao(descricao: str) -> str:
    line = descricao.strip().split("\n", 1)[0].strip()
    if not line:
        return "Solicitação do cliente"
    return line[:120] + ("…" if len(line) > 120 else "")


def enrich_ticket_from_triage(ticket: Ticket, triage: TriageResult) -> Ticket:
    """Alinha tipo/prioridade/título ao resultado da triagem (para RAG e exibição)."""
    prio = URGENCY_TO_PRIORIDADE.get(triage.urgency)
    if prio is None:
        raise ValueError(f"urgência não mapeável: {triage.urgency!r}")

    merged = dict(ticket)
    merged["tipo"] = triage.category
    merged["prioridade"] = prio
    merged["titulo"] = (
        triage.ticket_titulo.strip()
        if (triage.ticket_titulo and triage.ticket_titulo.strip())
        else _fallback_titulo_from_descricao(ticket["descricao"])
    )
    return merged


def triage_ticket(
    ticket: Ticket,
    *,
    logger: JsonlLogger,
    model: str = "gpt-4o-mini",
    feedback_memory: list[dict] | None = None,
) -> tuple[TriageResult | None, str | None]:
    """Retorna (resultado, erro). Se erro não for None, o fluxo deve ir direto ao humano."""
    with StepTimer(logger, "triage"):
        llm = ChatOpenAI(model=model, temperature=0)
        user = {
            "id": ticket["id"],
            "titulo": ticket["titulo"],
            "descricao": ticket["descricao"],
            "tipo": ticket["tipo"],
            "prioridade": ticket["prioridade"],
            "status": ticket["status"],
            "id_cliente": ticket["id_cliente"],
            "nome_cliente": ticket["nome_cliente"],
            "feedback_memory": feedback_memory or [],
        }

        raw = ""
        try:
            raw = llm.invoke(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ]
            ).content
            payload = json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            logger.log(
                "triage_failed",
                reason="invalid_json_response",
                error=str(e),
                raw_preview=raw[:500] if raw else "",
            )
            return None, f"Resposta do classificador não é JSON válido: {e}"

        parsed, err = _parse_triage_payload(payload, ticket)
        if err:
            logger.log("triage_failed", reason="validation", detail=err, raw_preview=str(payload)[:500])
            return None, err

        assert parsed is not None
        logger.log("triage_result", **asdict(parsed))
        return parsed, None
