from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_huggingface import HuggingFaceEmbeddings

from customer_success_ai.storage.sqlite import SQLiteRunStorage
from customer_success_ai.workflow.state import Ticket, WorkflowState


def _ticket_to_text(ticket: Ticket) -> str:
    return f"{ticket.get('titulo','')}\n{ticket.get('descricao','')}\nTipo: {ticket.get('tipo','')}".strip()


@dataclass(frozen=True)
class FeedbackSnippet:
    score: float
    category: str | None
    hil_decision: str
    ticket_text: str
    draft_before: str | None
    human_correction: str | None
    rejection_reason: str | None


class FeedbackMemory:
    def __init__(
        self,
        *,
        storage: SQLiteRunStorage,
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ):
        self.storage = storage
        self.embeddings = HuggingFaceEmbeddings(model_name=embedding_model)

    def embed_ticket(self, ticket: Ticket) -> list[float]:
        text = _ticket_to_text(ticket)
        vec = self.embeddings.embed_query(text)
        return [float(x) for x in vec]

    def record_from_state(
        self,
        *,
        state: WorkflowState,
        run_id: str,
        created_at_utc: str,
    ) -> None:
        if state.hil_decision not in ("rejeitar", "corrigir"):
            return

        ticket_text = _ticket_to_text(state.ticket)
        emb = self.embed_ticket(state.ticket)

        rejection_reason = None
        human_correction = None
        if state.hil_decision == "corrigir":
            human_correction = (state.hil_correction or "").strip() or None
        else:
            # Hoje o HIL não captura motivo de rejeição; guardamos um placeholder.
            rejection_reason = "rejeitado_sem_motivo_estruturado"

        triage_raw: dict[str, Any] | None = None
        if state.triage is not None:
            triage_raw = {
                "category": state.triage.category,
                "urgency": state.triage.urgency,
                "confidence": state.triage.confidence,
                "rationale": state.triage.rationale,
                "customer_id": state.triage.customer_id,
                "customer_name": state.triage.customer_name,
            }

        self.storage.save_feedback(
            created_at_utc=created_at_utc,
            run_id=run_id,
            ticket_id=state.ticket.get("id"),
            customer_id=state.ticket.get("id_cliente"),
            category=state.triage.category if state.triage is not None else None,
            hil_decision=state.hil_decision,
            ticket_text=ticket_text,
            draft_before=(state.draft or "").strip() or None,
            human_correction=human_correction,
            rejection_reason=rejection_reason,
            triage_raw=triage_raw,
            embedding=emb,
        )

    def retrieve(
        self,
        *,
        ticket: Ticket,
        category: str | None,
        limit: int = 3,
        min_score: float = 0.35,
    ) -> list[FeedbackSnippet]:
        emb = self.embed_ticket(ticket)
        rows = self.storage.search_feedback(query_embedding=emb, category=category, limit=max(limit, 1))
        out: list[FeedbackSnippet] = []
        for r in rows:
            score = float(r.get("score") or 0.0)
            if score < min_score:
                continue
            out.append(
                FeedbackSnippet(
                    score=score,
                    category=r.get("category"),
                    hil_decision=str(r.get("hil_decision") or ""),
                    ticket_text=str(r.get("ticket_text") or ""),
                    draft_before=r.get("draft_before"),
                    human_correction=r.get("human_correction"),
                    rejection_reason=r.get("rejection_reason"),
                )
            )
        return out[:limit]

    def format_for_prompt(self, snippets: list[FeedbackSnippet]) -> list[dict[str, Any]]:
        return [
            {
                "score": round(s.score, 3),
                "category": s.category,
                "hil_decision": s.hil_decision,
                "ticket_text": s.ticket_text[:800],
                "draft_before": (s.draft_before or "")[:1200] if s.draft_before else None,
                "human_correction": (s.human_correction or "")[:1200] if s.human_correction else None,
                "rejection_reason": s.rejection_reason,
            }
            for s in snippets
        ]

