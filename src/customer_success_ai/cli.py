from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver

from customer_success_ai.config import AppConfig
from customer_success_ai.observability import JsonlLogger, StepTimer
from urllib.parse import urlparse

from customer_success_ai.integrations.kb_api import normalize_api_base as normalize_kb_base
from customer_success_ai.integrations.kb_api import create_doc_url as kb_create_doc_url
from customer_success_ai.integrations.kb_api import search_url as kb_search_url
from customer_success_ai.integrations.tickets_api import health_url, historico_url, normalize_api_base
from customer_success_ai.integrations.tickets_mock_spawn import local_tickets_mock_session
from customer_success_ai.memory.feedback import FeedbackMemory
from customer_success_ai.mcp_backend.spawn import local_mcp_session
from customer_success_ai.storage.sqlite import SQLiteRunStorage
from customer_success_ai.workflow.graph import build_workflow_graph
from customer_success_ai.workflow.state import WorkflowState, Ticket
from customer_success_ai.triage.ticket_input import ticket_from_client_input
from customer_success_ai.triage.router import enrich_ticket_from_triage, triage_ticket


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _demo_ticket() -> Ticket:
    return {
        "id": "TKT-0008",
        "titulo": "Cliente com fatura em atraso",
        "descricao": "Divergência financeira identificada pelo cliente no extrato do mês.",
        "tipo": "financeira",
        "status": "aberto",
        "prioridade": "baixo",
        "responsavel": "Ana Lima",
        "id_cliente": "CLI-007",
        "nome_cliente": "Eta Consultoria",
        "criado_em": "2025-10-22T20:42:00",
        "atualizado_em": "2026-03-07T08:00:00",
    }


def _ticket_from_cli(cliente: str | None, descricao: str | None) -> Ticket:
    c = (cliente or "").strip()
    d = (descricao or "").strip()
    if c or d:
        if not c or not d:
            raise SystemExit("Para entrada do cliente informe ambos: --cliente e --descricao.")
        try:
            return ticket_from_client_input(c, d)
        except ValueError as e:
            raise SystemExit(str(e))
    return _demo_ticket()


def cmd_triagem(*, cliente: str, descricao: str) -> int:
    """Somente OpenAI + log local; não exige TICKETS_API_URL nem MCP."""
    load_dotenv(override=False)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Defina OPENAI_API_KEY no ambiente.")

    thread_id = str(uuid.uuid4())
    log_dir = Path(os.getenv("LOG_DIR", ".logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "customer-success-ai.jsonl"
    logger = JsonlLogger(path=log_path, thread_id=thread_id)

    try:
        ticket = ticket_from_client_input(cliente, descricao)
    except ValueError as e:
        raise SystemExit(str(e))

    print("Ticket mínimo (entrada)...")
    print(json.dumps(ticket, ensure_ascii=False, indent=2))

    result, err = triage_ticket(ticket, logger=logger)
    if err or result is None:
        print(f"\nTriagem falhou: {err}")
        return 1

    enriched = enrich_ticket_from_triage(ticket, result)
    out = {
        "triage": {
            "category": result.category,
            "urgency": result.urgency,
            "confidence": result.confidence,
            "rationale": result.rationale,
            "titulo_modelo": result.ticket_titulo,
        },
        "ticket_apos_triagem": enriched,
    }
    print("\nResultado:")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nLog: {log_path}")
    return 0


def _load_config() -> AppConfig:
    load_dotenv(override=False)
    log_dir = Path(os.getenv("LOG_DIR", ".logs"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    mocks_dir = Path(os.getenv("MOCKS_DIR", "mocks"))
    runs_db_path = Path(os.getenv("RUNS_DB_PATH", ".data/runs.sqlite"))
    checkpoints_db_path = Path(os.getenv("CHECKPOINTS_DB_PATH", ".data/checkpoints.sqlite"))

    raw_base = os.getenv("TICKETS_API_URL", "").strip()
    if not raw_base:
        raise SystemExit(
            "Defina TICKETS_API_URL no ambiente (ex.: http://127.0.0.1:8000/tickets). "
            "O cliente chama /historico e /health relativos a essa base."
        )
    base = normalize_api_base(raw_base)
    # KB usa o mesmo servidor mock; por padrão deriva de TICKETS_API_URL trocando /tickets por /kb.
    raw_kb = os.getenv("KB_API_URL", "").strip()
    if raw_kb:
        kb_base = normalize_kb_base(raw_kb)
    else:
        u = urlparse(base)
        kb_base = f"{u.scheme}://{u.netloc}/kb"

    return AppConfig(
        log_dir=log_dir,
        log_level=log_level,
        mocks_dir=mocks_dir,
        runs_db_path=runs_db_path,
        checkpoints_db_path=checkpoints_db_path,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        tickets_api_base=base,
        tickets_historico_url=historico_url(base),
        tickets_health_url=health_url(base),
        kb_api_base=kb_base,
        kb_search_url=kb_search_url(kb_base),
        kb_create_url=kb_create_doc_url(kb_base),
    )


def _invoke_workflow(
    config: AppConfig,
    logger: JsonlLogger,
    ticket: Ticket,
    feedback_memory: FeedbackMemory,
    thread_id: str,
    *,
    hil_mode: str = "interactive",
    hil_correction: str | None = None,
    kb_offer: str | None = None,
    kb_validate: str | None = None,
):
    mcp_url = (os.getenv("MCP_URL", "") or "").strip()
    if not mcp_url:
        raise SystemExit("Defina MCP_URL no ambiente (ex.: http://127.0.0.1:8000/mcp).")

    def _run_graph():
        with SqliteSaver.from_conn_string(str(config.checkpoints_db_path)) as checkpointer:
            graph = build_workflow_graph(
                logger=logger,
                feedback_memory=feedback_memory,
                checkpointer=checkpointer,
                hil_mode=hil_mode,
                hil_correction=hil_correction,
                kb_offer=kb_offer,
                kb_validate=kb_validate,
            )
            cfg = {"configurable": {"thread_id": thread_id}}
            return graph.invoke(WorkflowState(ticket=ticket, as_of_utc=_utc_now_iso()), cfg)

    # Ordem correta em dev local:
    # 1) subir backend HTTP (tickets+kb mock) se aplicável
    # 2) subir MCP (que depende do backend HTTP)
    # 3) executar grafo (que chama MCP via integrations/loader.py)
    with local_tickets_mock_session(config.tickets_api_base, config.tickets_health_url):
        with local_mcp_session(tickets_api_url=config.tickets_api_base, mcp_url=mcp_url):
            return _run_graph()

def run(*, cliente: str | None = None, descricao: str | None = None) -> int:
    config = _load_config()
    thread_id = str(uuid.uuid4())
    log_path = config.log_dir / "customer-success-ai.jsonl"
    logger = JsonlLogger(path=log_path, thread_id=thread_id)
    storage = SQLiteRunStorage(config.runs_db_path)
    storage.init()
    memory = FeedbackMemory(storage=storage)

    print("Iniciando customer-success-ai...")

    ticket = _ticket_from_cli(cliente, descricao)

    with StepTimer(logger, "bootstrap"):
        logger.log(
            "run_start",
            log_dir=str(config.log_dir),
            log_level=config.log_level,
            mocks_dir=str(config.mocks_dir.as_posix()),
            tickets_api_base=config.tickets_api_base,
            kb_api_base=config.kb_api_base,
        )

    with StepTimer(logger, "graph_invoke"):
        result = _invoke_workflow(config, logger, ticket, memory, thread_id, hil_mode="interactive")

    with StepTimer(logger, "shutdown"):
        state = result if isinstance(result, WorkflowState) else WorkflowState(**result)
        storage.save_run(run_id=thread_id, created_at_utc=_utc_now_iso(), state=state)
        memory.record_from_state(state=state, run_id=thread_id, created_at_utc=_utc_now_iso())
        hil_decision = result["hil_decision"] if isinstance(result, dict) else result.hil_decision
        kb_req = result.get("kb_generate_requested") if isinstance(result, dict) else result.kb_generate_requested
        kb_val = result.get("kb_validation_decision") if isinstance(result, dict) else result.kb_validation_decision
        logger.log(
            "run_end",
            status="ok",
            hil_decision=hil_decision,
            kb_generate_requested=kb_req,
            kb_validation_decision=kb_val,
        )
        print(f"\nFinalizado. thread_id={thread_id}")
        print(f"Decisão HIL: {hil_decision}")
        if kb_req is not None:
            print(f"Geração KB solicitada: {'sim' if kb_req else 'não'}")
        if kb_val is not None:
            print(f"Validação KB (humano): {kb_val}")
        print(f"Log: {log_path}")
        print(f"Runs DB: {config.runs_db_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="customer-success-ai")
    sub = parser.add_subparsers(dest="cmd")
    p_run = sub.add_parser("run", help="Executa o fluxo")
    p_mcp = sub.add_parser("mcp", help="Sobe o backend MCP (KB + Tickets)")
    p_triagem = sub.add_parser(
        "triagem",
        help="Só triagem LLM a partir do nome do cliente e da descrição (sem workflow completo).",
    )
    p_triagem.add_argument("--cliente", required=True, help="Nome do cliente")
    p_triagem.add_argument("--descricao", required=True, help="Descrição do problema")
    p_run.add_argument("--cliente", default=None, help="Nome do cliente (use com --descricao)")
    p_run.add_argument("--descricao", default=None, help="Descrição do problema (use com --cliente)")
    p_run.add_argument(
        "--hil",
        default="interactive",
        choices=["interactive", "aprovar", "rejeitar", "corrigir"],
        help="Modo de HIL (interactive ou decisão direta)",
    )
    p_run.add_argument("--correcao", default="", help="Texto de correção quando --hil=corrigir")
    p_run.add_argument(
        "--gerar-kb",
        choices=["sim", "nao"],
        default=None,
        help="Somente modo não-interativo com --hil=aprovar: sim/nao gera artefato de KB after HIL.",
    )
    p_run.add_argument(
        "--validar-kb",
        choices=["aprovar", "rejeitar"],
        default=None,
        help="Somente modo não-interativo com --gerar-kb=sim: decisão na validação do artigo KB.",
    )

    args = parser.parse_args(argv)
    if args.cmd == "mcp":
        # Backend MCP (Streamable HTTP).
        # O servidor usa TICKETS_API_URL/KB_API_URL do ambiente, igual ao app.
        from customer_success_ai.mcp_backend.server import main as mcp_main

        mcp_main()
        return 0

    if args.cmd == "triagem":
        return cmd_triagem(cliente=args.cliente, descricao=args.descricao)

    if args.cmd in (None, "run"):
        cliente = getattr(args, "cliente", None)
        descricao = getattr(args, "descricao", None)
        hil_mode = getattr(args, "hil", "interactive")
        if hil_mode == "interactive":
            return run(cliente=cliente, descricao=descricao)

        # Execução não-interativa para smoke tests / pipelines.
        config = _load_config()
        thread_id = str(uuid.uuid4())
        log_path = config.log_dir / "customer-success-ai.jsonl"
        logger = JsonlLogger(path=log_path, thread_id=thread_id)
        storage = SQLiteRunStorage(config.runs_db_path)
        storage.init()
        memory = FeedbackMemory(storage=storage)

        ticket = _ticket_from_cli(cliente, descricao)

        result = _invoke_workflow(
            config,
            logger,
            ticket,
            memory,
            thread_id,
            hil_mode=args.hil,
            hil_correction=(args.correcao if getattr(args, "correcao", "") else None),
            kb_offer=getattr(args, "gerar_kb", None),
            kb_validate=getattr(args, "validar_kb", None),
        )
        hil_decision = result["hil_decision"] if isinstance(result, dict) else result.hil_decision
        kb_req = result["kb_generate_requested"] if isinstance(result, dict) else result.kb_generate_requested
        kb_val = result["kb_validation_decision"] if isinstance(result, dict) else result.kb_validation_decision
        print(f"Finalizado. Decisão HIL: {hil_decision}")
        if kb_req is not None:
            print(f"Geração KB solicitada: {'sim' if kb_req else 'não'}")
        if kb_val is not None:
            print(f"Validação KB (humano): {kb_val}")
        logger.log(
            "run_end",
            status="ok",
            hil_decision=hil_decision,
            kb_generate_requested=kb_req,
            kb_validation_decision=kb_val,
        )
        state = result if isinstance(result, WorkflowState) else WorkflowState(**result)
        storage.save_run(run_id=thread_id, created_at_utc=_utc_now_iso(), state=state)
        memory.record_from_state(state=state, run_id=thread_id, created_at_utc=_utc_now_iso())
        print(f"Log: {log_path}")
        print(f"Runs DB: {config.runs_db_path}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
