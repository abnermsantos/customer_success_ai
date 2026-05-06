from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from customer_success_ai.mocks.loader import load_tickets_history
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.rag.retriever import retrieve_context
from customer_success_ai.triage.router import triage_ticket
from customer_success_ai.workflow.state import WorkflowState


def _count_open_tickets_for_customer(history: list[dict], customer_id: str) -> int:
    # Regra acordada: todo ticket que não esteja "finalizado" é considerado vivo/aberto.
    return sum(1 for t in history if t.get("id_cliente") == customer_id and t.get("status") != "finalizado")


def _node_consult_mocks(state: WorkflowState, *, logger: JsonlLogger, kb_dir: Path, history_path: Path) -> WorkflowState:
    with StepTimer(logger, "consult_mocks"):
        history = load_tickets_history(history_path)
        open_count = _count_open_tickets_for_customer(history, state.ticket["id_cliente"])

        state.open_tickets_for_customer = open_count
        # Regra inicial (provisória): sensível quando o cliente possui qualquer ticket vivo.
        # Quando definirmos "top N / limiar X", substituímos aqui.
        state.is_sensitive = open_count > 0
        return state


def _node_triage(state: WorkflowState, *, logger: JsonlLogger) -> WorkflowState:
    result = triage_ticket(state.ticket, logger=logger)
    state.triage = result
    return state


def _node_rag_and_draft(state: WorkflowState, *, logger: JsonlLogger, kb_dir: Path, history_path: Path) -> WorkflowState:
    docs, citations = retrieve_context(state.ticket, kb_dir=kb_dir, history_path=history_path, logger=logger)
    state.citations = [c.__dict__ for c in citations]

    # Confiança simples: usa a confiança da triagem quando existir, senão 0.5.
    state.confidence = state.triage.confidence if state.triage else 0.5
    state.requires_human_review = state.is_sensitive or state.confidence < 0.6

    triage_line = ""
    if state.triage:
        triage_line = f"Triagem: {state.triage.category} | Urgência: {state.triage.urgency} | Confiança: {state.triage.confidence:.2f}\n"

    sources_text = "\n".join(
        f"- [{c.source}] {c.ref}" + (f" ({c.path})" if c.path else "") for c in citations
    )

    state.draft = (
        f"{triage_line}"
        f"Ticket {state.ticket['id']} ({state.ticket['tipo']}): {state.ticket['titulo']}\n"
        f"Cliente: {state.ticket['nome_cliente']} ({state.ticket['id_cliente']})\n"
        f"Resumo: {state.ticket['descricao']}\n\n"
        "Resposta sugerida (rascunho):\n"
        "- Validar a divergência no extrato e solicitar evidências (print/linha do extrato).\n"
        "- Conferir cobranças/conciliação e, se aplicável, orientar sobre reembolso/ajuste.\n\n"
        "Fontes consultadas (citações):\n"
        f"{sources_text}\n\n"
        f"Confiança: {state.confidence:.2f}\n"
        f"Requer revisão humana: {'SIM' if state.requires_human_review else 'NÃO'}\n"
    )
    return state


def _node_hil(state: WorkflowState, *, logger: JsonlLogger) -> WorkflowState:
    with StepTimer(logger, "hil"):
        print("\n=== RASCUNHO ===")
        print(state.draft)
        print("Requer revisão humana:", "SIM" if state.requires_human_review else "NÃO")
        print(f"Tickets vivos do cliente (histórico mock): {state.open_tickets_for_customer}")

        while True:
            choice = input("\nHIL - escolha: [a]provar, [r]ejeitar, [c]orrigir: ").strip().lower()
            if choice in ("a", "aprovar"):
                state.hil_decision = "aprovar"
                break
            if choice in ("r", "rejeitar"):
                state.hil_decision = "rejeitar"
                break
            if choice in ("c", "corrigir"):
                state.hil_decision = "corrigir"
                state.hil_correction = input("Digite a correção do analista: ").strip()
                break
            print("Opção inválida. Tente novamente.")

        logger.log("hil_decision", decision=state.hil_decision, correction=state.hil_correction)
        return state


def build_workflow_graph(
    *,
    logger: JsonlLogger,
    kb_dir: Path,
    history_path: Path,
    hil_mode: str = "interactive",
    hil_correction: str | None = None,
):
    g = StateGraph(WorkflowState)
    g.add_node("consult_mocks", lambda s: _node_consult_mocks(s, logger=logger, kb_dir=kb_dir, history_path=history_path))
    g.add_node("triage", lambda s: _node_triage(s, logger=logger))
    g.add_node("rag_and_draft", lambda s: _node_rag_and_draft(s, logger=logger, kb_dir=kb_dir, history_path=history_path))

    def hil_node(s: WorkflowState) -> WorkflowState:
        if hil_mode == "interactive":
            return _node_hil(s, logger=logger)
        with StepTimer(logger, "hil"):
            if hil_mode not in ("aprovar", "rejeitar", "corrigir"):
                raise ValueError(f"hil_mode inválido: {hil_mode}")
            s.hil_decision = hil_mode  # type: ignore[assignment]
            if hil_mode == "corrigir":
                s.hil_correction = hil_correction or ""
            logger.log("hil_decision", decision=s.hil_decision, correction=s.hil_correction, mode="non_interactive")
            return s

    g.add_node("hil", hil_node)
    g.set_entry_point("consult_mocks")
    g.add_edge("consult_mocks", "triage")
    g.add_edge("triage", "rag_and_draft")
    g.add_edge("rag_and_draft", "hil")
    g.add_edge("hil", END)
    return g.compile()

