from __future__ import annotations

import json
from dataclasses import asdict

from langchain_openai import ChatOpenAI

from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.triage.models import TriageResult
from customer_success_ai.workflow.state import Ticket


SYSTEM = """Você é um agente classificador de tickets de Customer Success.
Tarefa: dado um ticket em português, classifique:
- category: uma de ["técnica","comercial","financeira","escalação"]
- urgency: inteiro 1..4 (1=mais urgente, 4=menos urgente)
- confidence: float 0..1
- rationale: 1 frase curta justificando

Responda SOMENTE em JSON válido com as chaves: category, urgency, confidence, rationale.
"""


def triage_ticket(ticket: Ticket, *, logger: JsonlLogger, model: str = "gpt-4o-mini") -> TriageResult:
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
        }
        raw = llm.invoke(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ]
        ).content

        data = json.loads(raw)
        result = TriageResult(
            category=data["category"],
            urgency=int(data["urgency"]),
            customer_id=ticket["id_cliente"],
            customer_name=ticket["nome_cliente"],
            confidence=float(data["confidence"]),
            rationale=str(data["rationale"]),
        )
        logger.log("triage_result", **asdict(result))
        return result

