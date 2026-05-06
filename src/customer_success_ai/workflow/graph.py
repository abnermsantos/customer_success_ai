from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from customer_success_ai.mocks.loader import load_kb_docs, load_tickets_history
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.workflow.state import WorkflowState


def _count_open_tickets_for_customer(history: list[dict], customer_id: str) -> int:
    # Regra acordada: todo ticket que não esteja "finalizado" é considerado vivo/aberto.
    return sum(1 for t in history if t.get("id_cliente") == customer_id and t.get("status") != "finalizado")


def _node_consult_mocks(state: WorkflowState, *, logger: JsonlLogger, kb_dir: Path, history_path: Path) -> WorkflowState:
    with StepTimer(logger, "consult_mocks"):
        kb_docs = load_kb_docs(kb_dir)
        history = load_tickets_history(history_path)
        open_count = _count_open_tickets_for_customer(history, state.ticket["id_cliente"])

        state.open_tickets_for_customer = open_count
        state.is_sensitive = open_count > 0  # refinamos a regra (top N/limiar) quando definirmos

        state.consulted_sources = [
            {"source": "kb_markdown", "items": len(kb_docs), "path": str(kb_dir.as_posix())},
            {"source": "tickets_json", "items": len(history), "path": str(history_path.as_posix())},
        ]
        logger.log(
            "sources_consulted",
            sources=state.consulted_sources,
            open_tickets_for_customer=open_count,
            customer_id=state.ticket["id_cliente"],
        )

        state.draft = (
            f"Ticket {state.ticket['id']} ({state.ticket['tipo']}): {state.ticket['titulo']}\n"
            f"Cliente: {state.ticket['nome_cliente']} ({state.ticket['id_cliente']})\n"
            f"Resumo: {state.ticket['descricao']}\n\n"
            "Contexto: fontes consultadas registradas no log.\n"
        )
        state.requires_human_review = state.is_sensitive
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
    g.add_edge("consult_mocks", "hil")
    g.add_edge("hil", END)
    return g.compile()

