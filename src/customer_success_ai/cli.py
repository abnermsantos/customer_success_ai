from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver

from customer_success_ai.config import AppConfig
from customer_success_ai.mocks.loader import tickets_historico_loader
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.mocks.tickets_api import health_url, historico_url, normalize_api_base
from customer_success_ai.mocks.tickets_mock_spawn import local_tickets_mock_session
from customer_success_ai.memory.feedback import FeedbackMemory
from customer_success_ai.storage.sqlite import SQLiteRunStorage
from customer_success_ai.workflow.graph import build_workflow_graph
from customer_success_ai.workflow.state import WorkflowState, Ticket


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config() -> AppConfig:
    load_dotenv(override=False)
    log_dir = Path(os.getenv("LOG_DIR", ".logs"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    mocks_dir = Path(os.getenv("MOCKS_DIR", "mocks"))
    kb_dir = mocks_dir / "base_conhecimento"
    runs_db_path = Path(os.getenv("RUNS_DB_PATH", ".data/runs.sqlite"))
    checkpoints_db_path = Path(os.getenv("CHECKPOINTS_DB_PATH", ".data/checkpoints.sqlite"))

    raw_base = os.getenv("TICKETS_API_URL", "").strip()
    if not raw_base:
        raise SystemExit(
            "Defina TICKETS_API_URL no ambiente (ex.: http://127.0.0.1:8000/tickets). "
            "O cliente chama /historico e /health relativos a essa base."
        )
    base = normalize_api_base(raw_base)

    return AppConfig(
        log_dir=log_dir,
        log_level=log_level,
        mocks_dir=mocks_dir,
        kb_dir=kb_dir,
        runs_db_path=runs_db_path,
        checkpoints_db_path=checkpoints_db_path,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        tickets_api_base=base,
        tickets_historico_url=historico_url(base),
        tickets_health_url=health_url(base),
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
    with local_tickets_mock_session(config.tickets_api_base, config.tickets_health_url):
        load_history = tickets_historico_loader(config.tickets_historico_url)
        with SqliteSaver.from_conn_string(str(config.checkpoints_db_path)) as checkpointer:
            graph = build_workflow_graph(
                logger=logger,
                kb_dir=config.kb_dir,
                load_history=load_history,
                feedback_memory=feedback_memory,
                checkpointer=checkpointer,
                hil_mode=hil_mode,
                hil_correction=hil_correction,
                kb_offer=kb_offer,
                kb_validate=kb_validate,
            )
            cfg = {"configurable": {"thread_id": thread_id}}
            return graph.invoke(WorkflowState(ticket=ticket), cfg)


def run() -> int:
    config = _load_config()
    thread_id = str(uuid.uuid4())
    log_path = config.log_dir / "customer-success-ai.jsonl"
    logger = JsonlLogger(path=log_path, thread_id=thread_id)
    storage = SQLiteRunStorage(config.runs_db_path)
    storage.init()
    memory = FeedbackMemory(storage=storage)

    print("Iniciando customer-success-ai...")

    ticket: Ticket = {
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

    with StepTimer(logger, "bootstrap"):
        logger.log(
            "run_start",
            log_dir=str(config.log_dir),
            log_level=config.log_level,
            mocks_dir=str(config.mocks_dir.as_posix()),
            tickets_api_base=config.tickets_api_base,
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
    if args.cmd in (None, "run"):
        if args.hil == "interactive":
            return run()

        # Execução não-interativa para smoke tests / pipelines.
        config = _load_config()
        thread_id = str(uuid.uuid4())
        log_path = config.log_dir / "customer-success-ai.jsonl"
        logger = JsonlLogger(path=log_path, thread_id=thread_id)
        storage = SQLiteRunStorage(config.runs_db_path)
        storage.init()
        memory = FeedbackMemory(storage=storage)

        ticket: Ticket = {
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

        result = _invoke_workflow(
            config,
            logger,
            ticket,
            memory,
            thread_id,
            hil_mode=args.hil,
            hil_correction=args.correcao if args.correcao else None,
            kb_offer=args.gerar_kb,
            kb_validate=args.validar_kb,
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
