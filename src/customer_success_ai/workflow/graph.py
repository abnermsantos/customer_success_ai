from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.rag.retriever import retrieve_context
from customer_success_ai.agents.kb_generator import generate_kb_article
from customer_success_ai.agents.specialists import run_specialist
from customer_success_ai.mocks.loader import create_kb_doc
from customer_success_ai.memory.feedback import FeedbackMemory
from customer_success_ai.triage.router import triage_ticket
from customer_success_ai.workflow.state import WorkflowState


def _count_open_tickets_for_customer(history: list[dict], customer_id: str) -> int:
    # Regra acordada: todo ticket que não esteja "finalizado" é considerado vivo/aberto.
    return sum(1 for t in history if t.get("id_cliente") == customer_id and t.get("status") != "finalizado")


def _node_consult_mocks(
    state: WorkflowState,
    *,
    logger: JsonlLogger,
    load_history: Callable[[], list[dict[str, Any]]],
) -> WorkflowState:
    with StepTimer(logger, "consult_mocks"):
        history = load_history()
        open_count = _count_open_tickets_for_customer(history, state.ticket["id_cliente"])

        state.open_tickets_for_customer = open_count
        # Regra inicial (provisória): sensível quando o cliente possui qualquer ticket vivo.
        # Quando definirmos "top N / limiar X", substituímos aqui.
        state.is_sensitive = open_count > 0
        return state


def _node_triage(state: WorkflowState, *, logger: JsonlLogger, feedback_memory: FeedbackMemory | None) -> WorkflowState:
    triage_fb = None
    if feedback_memory is not None:
        triage_fb = feedback_memory.format_for_prompt(
            feedback_memory.retrieve(ticket=state.ticket, category=None, limit=3, min_score=0.35)
        )
    result, err = triage_ticket(state.ticket, logger=logger, feedback_memory=triage_fb)
    if err:
        state.triage = None
        state.classification_error = err
    else:
        state.triage = result
        state.classification_error = None
    return state


def _route_after_triage(state: WorkflowState) -> str:
    """Tickets não classificáveis não passam por RAG/workers para evitar ciclos e desperdício."""
    if state.triage is None or state.classification_error:
        return "human_direct"
    return "rag_and_draft"


def _node_human_direct(state: WorkflowState, *, logger: JsonlLogger) -> WorkflowState:
    with StepTimer(logger, "human_direct"):
        reason = state.classification_error or "Classificação indisponível."
        logger.log("route_human_direct", reason=reason, ticket_id=state.ticket["id"])
        state.specialist = None
        state.citations = []
        state.confidence = 0.0
        state.requires_human_review = True
        state.draft = (
            "CLASSIFICAÇÃO AUTOMÁTICA INDISPONÍVEL\n\n"
            f"Mensagem técnica: {reason}\n\n"
            f"Ticket {state.ticket['id']} ({state.ticket['tipo']}): {state.ticket['titulo']}\n"
            f"Cliente: {state.ticket['nome_cliente']} ({state.ticket['id_cliente']})\n"
            f"Resumo: {state.ticket['descricao']}\n\n"
            "O sistema não atribuiu este ticket a nenhum agente especialista. "
            "Conduza a triagem e a resposta manualmente.\n\n"
            f"Tickets vivos do cliente: {state.open_tickets_for_customer}\n"
            f"Requer revisão humana: SIM\n"
        )
    return state


def _node_rag_and_draft(
    state: WorkflowState,
    *,
    logger: JsonlLogger,
    kb_search_url: str,
    load_history: Callable[[], list[dict[str, Any]]],
) -> WorkflowState:
    docs, citations = retrieve_context(state.ticket, kb_search_url=kb_search_url, load_history=load_history, logger=logger)
    state.citations = [c.__dict__ for c in citations]
    return state


def _node_worker(state: WorkflowState, *, logger: JsonlLogger, feedback_memory: FeedbackMemory | None) -> WorkflowState:
    if not state.triage:
        raise ValueError("triage ausente no estado")

    state.specialist = state.triage.category
    specialist_fb = None
    if feedback_memory is not None:
        specialist_fb = feedback_memory.format_for_prompt(
            feedback_memory.retrieve(ticket=state.ticket, category=state.triage.category, limit=3, min_score=0.35)
        )
    out = run_specialist(
        state.ticket,
        triage=state.triage,
        citations=state.citations,
        is_sensitive=state.is_sensitive,
        logger=logger,
        feedback_memory=specialist_fb,
    )
    state.confidence = out.confidence
    state.requires_human_review = state.is_sensitive or out.requires_human_review or state.confidence < 0.6

    triage_line = f"Triagem: {state.triage.category} | Urgência: {state.triage.urgency} | Confiança(triagem): {state.triage.confidence:.2f}\n"
    citations_text = "\n".join(
        f"- [{c.get('source')}] {c.get('ref')}" + (f" ({c.get('path')})" if c.get("path") else "")
        for c in state.citations
    )

    state.draft = (
        f"{triage_line}"
        f"Especialista acionado: {state.specialist}\n\n"
        f"Ticket {state.ticket['id']} ({state.ticket['tipo']}): {state.ticket['titulo']}\n"
        f"Cliente: {state.ticket['nome_cliente']} ({state.ticket['id_cliente']})\n"
        f"Resumo: {state.ticket['descricao']}\n\n"
        "Resposta sugerida (rascunho):\n"
        f"{out.draft}\n\n"
        "Fontes consultadas (citações):\n"
        f"{citations_text}\n\n"
        f"Confiança: {state.confidence:.2f}\n"
        f"Requer revisão humana: {'SIM' if state.requires_human_review else 'NÃO'}\n"
        f"Motivo: {out.rationale}\n"
    )
    logger.log("worker_selected", category=state.specialist)
    return state


def _route_by_category(state: WorkflowState) -> str:
    if not state.triage:
        return "worker_default"
    if state.triage.category == "técnica":
        return "worker_tecnica"
    if state.triage.category == "comercial":
        return "worker_comercial"
    if state.triage.category == "financeira":
        return "worker_financeira"
    if state.triage.category == "escalação":
        return "worker_escalacao"
    return "worker_default"


def _node_hil(state: WorkflowState, *, logger: JsonlLogger) -> WorkflowState:
    with StepTimer(logger, "hil"):
        print("\n=== RASCUNHO ===")
        print(state.draft)
        print("Requer revisão humana:", "SIM" if state.requires_human_review else "NÃO")
        print(f"Tickets vivos do cliente (histórico): {state.open_tickets_for_customer}")

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


def _route_after_hil(state: WorkflowState) -> str | object:
    """Só segue para oferta de KB se o analista aprovou o rascunho da resposta."""
    if state.hil_decision != "aprovar":
        return END
    return "hil_kb_offer"


def _node_hil_kb_offer(
    state: WorkflowState,
    *,
    logger: JsonlLogger,
    non_interactive: bool,
    kb_offer: str | None,
) -> WorkflowState:
    with StepTimer(logger, "hil_kb_offer"):
        if not non_interactive:
            while True:
                choice = input(
                    "\nDeseja gerar documentação para a base de conhecimento "
                    "(como finalizar este tipo de ticket)? [s]im / [n]ão: "
                ).strip().lower()
                if choice in ("s", "sim", "y", "yes"):
                    state.kb_generate_requested = True
                    break
                if choice in ("n", "não", "nao", "no"):
                    state.kb_generate_requested = False
                    break
                print("Digite sim ou não (s ou n).")
        else:
            state.kb_generate_requested = kb_offer == "sim"
        logger.log(
            "kb_offer_answer",
            requested=state.kb_generate_requested,
            mode="non_interactive" if non_interactive else "interactive",
        )
    return state


def _route_after_kb_offer(state: WorkflowState) -> str | object:
    if state.kb_generate_requested:
        return "kb_generator"
    return END


def _node_kb_generator(state: WorkflowState, *, logger: JsonlLogger) -> WorkflowState:
    try:
        state.kb_article_markdown = generate_kb_article(state, logger=logger)
    except Exception as e:
        logger.log("kb_generation_failed", error=str(e), ticket_id=state.ticket["id"])
        state.kb_article_markdown = (
            "---\nid: KB-ERRO\ntitle: \"Falha ao gerar rascunho de KB\"\n"
            "category: técnica\ntags: [kb, erro, geracao]\nmodule: sistema\naudience: interno\n---\n\n"
            f"# Falha ao gerar artigo\n\n```\n{e}\n```\n\nRejeitar este rascunho e tentar novamente.\n"
        )
    return state


def _node_hil_kb_validate(
    state: WorkflowState,
    *,
    logger: JsonlLogger,
    non_interactive: bool,
    kb_validate: str | None,
) -> WorkflowState:
    with StepTimer(logger, "hil_kb_validate"):
        md = state.kb_article_markdown or ""
        print("\n=== RASCUNHO DE ARTIGO PARA KB (validação humana) ===")
        print(md)
        print("=== FIM DO ARTIGO ===\n")

        if not non_interactive:
            while True:
                choice = input("Validação do artigo KB — [a]provar uso/publicação ou [r]ejeitar rascunho: ").strip().lower()
                if choice in ("a", "aprovar"):
                    state.kb_validation_decision = "aprovar"
                    break
                if choice in ("r", "rejeitar"):
                    state.kb_validation_decision = "rejeitar"
                    break
                print("Opção inválida. Escolha a ou r.")
        else:
            val = kb_validate if kb_validate in ("aprovar", "rejeitar") else "aprovar"
            state.kb_validation_decision = val  # type: ignore[assignment]
            logger.log("kb_human_validation", decision=val, mode="non_interactive")
            return state

        logger.log("kb_human_validation", decision=state.kb_validation_decision, mode="interactive")

    return state


def _node_kb_persist(state: WorkflowState, *, logger: JsonlLogger, kb_create_url: str) -> WorkflowState:
    md = state.kb_article_markdown or ""
    if not md.strip().startswith("---"):
        logger.log("kb_persist_skipped", reason="empty_or_no_frontmatter", ticket_id=state.ticket["id"])
        return state
    with StepTimer(logger, "kb_persist"):
        out = create_kb_doc(kb_create_url, markdown=md, timeout=120.0)
        logger.log("kb_persisted", **out)
    return state


def _route_after_kb_validate(state: WorkflowState) -> str | object:
    if state.kb_validation_decision == "aprovar":
        return "kb_persist"
    return END


def build_workflow_graph(
    *,
    logger: JsonlLogger,
    kb_search_url: str,
    kb_create_url: str,
    load_history: Callable[[], list[dict[str, Any]]],
    feedback_memory: FeedbackMemory | None = None,
    checkpointer: Any | None = None,
    hil_mode: str = "interactive",
    hil_correction: str | None = None,
    kb_offer: str | None = None,
    kb_validate: str | None = None,
):
    g = StateGraph(WorkflowState)
    g.add_node(
        "consult_mocks",
        lambda s: _node_consult_mocks(s, logger=logger, load_history=load_history),
    )
    g.add_node("triage", lambda s: _node_triage(s, logger=logger, feedback_memory=feedback_memory))
    g.add_node("human_direct", lambda s: _node_human_direct(s, logger=logger))
    g.add_node(
        "rag_and_draft",
        lambda s: _node_rag_and_draft(s, logger=logger, kb_search_url=kb_search_url, load_history=load_history),
    )
    g.add_node("worker_tecnica", lambda s: _node_worker(s, logger=logger, feedback_memory=feedback_memory))
    g.add_node("worker_comercial", lambda s: _node_worker(s, logger=logger, feedback_memory=feedback_memory))
    g.add_node("worker_financeira", lambda s: _node_worker(s, logger=logger, feedback_memory=feedback_memory))
    g.add_node("worker_escalacao", lambda s: _node_worker(s, logger=logger, feedback_memory=feedback_memory))
    g.add_node("worker_default", lambda s: _node_worker(s, logger=logger, feedback_memory=feedback_memory))

    non_interactive = hil_mode != "interactive"

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

    def kb_offer_node(s: WorkflowState) -> WorkflowState:
        return _node_hil_kb_offer(s, logger=logger, non_interactive=non_interactive, kb_offer=kb_offer)

    def kb_gen_node(s: WorkflowState) -> WorkflowState:
        return _node_kb_generator(s, logger=logger)

    def kb_validate_node(s: WorkflowState) -> WorkflowState:
        kb_val = kb_validate
        if non_interactive and kb_offer == "sim" and kb_val is None:
            kb_val = "aprovar"
        return _node_hil_kb_validate(
            s,
            logger=logger,
            non_interactive=non_interactive,
            kb_validate=kb_val,
        )

    g.add_node("hil", hil_node)
    g.add_node("hil_kb_offer", kb_offer_node)
    g.add_node("kb_generator", kb_gen_node)
    g.add_node("hil_kb_validate", kb_validate_node)
    g.add_node("kb_persist", lambda s: _node_kb_persist(s, logger=logger, kb_create_url=kb_create_url))
    g.set_entry_point("consult_mocks")
    g.add_edge("consult_mocks", "triage")
    g.add_conditional_edges("triage", _route_after_triage)
    g.add_edge("human_direct", "hil")
    g.add_conditional_edges("rag_and_draft", _route_by_category)
    g.add_edge("worker_tecnica", "hil")
    g.add_edge("worker_comercial", "hil")
    g.add_edge("worker_financeira", "hil")
    g.add_edge("worker_escalacao", "hil")
    g.add_edge("worker_default", "hil")
    g.add_conditional_edges("hil", _route_after_hil)
    g.add_conditional_edges("hil_kb_offer", _route_after_kb_offer)
    g.add_edge("kb_generator", "hil_kb_validate")
    g.add_conditional_edges("hil_kb_validate", _route_after_kb_validate)
    g.add_edge("kb_persist", END)
    return g.compile(checkpointer=checkpointer)

