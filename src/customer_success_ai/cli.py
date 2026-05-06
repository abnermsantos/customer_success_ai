from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from customer_success_ai.config import AppConfig
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.workflow.graph import build_workflow_graph
from customer_success_ai.workflow.state import WorkflowState, Ticket


def _load_config() -> AppConfig:
    load_dotenv(override=False)
    log_dir = Path(os.getenv("LOG_DIR", ".logs"))
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    mocks_dir = Path(os.getenv("MOCKS_DIR", "mocks"))
    tickets_history_path = mocks_dir / "tickets" / "tickets_historico_mock.json"
    kb_dir = mocks_dir / "base_conhecimento"
    return AppConfig(
        log_dir=log_dir,
        log_level=log_level,
        mocks_dir=mocks_dir,
        tickets_history_path=tickets_history_path,
        kb_dir=kb_dir,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )


def run() -> int:
    config = _load_config()
    thread_id = str(uuid.uuid4())
    log_path = config.log_dir / "customer-success-ai.jsonl"
    logger = JsonlLogger(path=log_path, thread_id=thread_id)

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
        )

    # Modo padrão: interativo (HIL via input()). Para execuções automatizadas, use CLI flag.
    graph = build_workflow_graph(
        logger=logger,
        kb_dir=config.kb_dir,
        history_path=config.tickets_history_path,
    )
    state = WorkflowState(ticket=ticket)

    with StepTimer(logger, "graph_invoke"):
        result = graph.invoke(state)

    with StepTimer(logger, "shutdown"):
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

        graph = build_workflow_graph(
            logger=logger,
            kb_dir=config.kb_dir,
            history_path=config.tickets_history_path,
            hil_mode=args.hil,
            hil_correction=args.correcao if args.correcao else None,
            kb_offer=args.gerar_kb,
            kb_validate=args.validar_kb,
        )
        state = WorkflowState(ticket=ticket)
        result = graph.invoke(state)
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
        print(f"Log: {log_path}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

