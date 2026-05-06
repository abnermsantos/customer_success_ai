from __future__ import annotations

import json
import re
from dataclasses import asdict

from langchain_openai import ChatOpenAI

from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.workflow.state import WorkflowState


SYSTEM = """Você é o agente de Documentação da Base de Conhecimento interna.
Recebe o histórico de um ticket já revisado pelo analista e deve produzir UM único arquivo Markdown
no formato usado pela empresa: começar com frontmatter YAML (--- ... ---), depois corpo markdown.

Campos obrigatórios do frontmatter (use aspas onde fizer sentido):
- id: string curta única para o artigo, prefixo sug. GEN- + síntese ou ticket (ex.: GEN-FIN-div-extrato)
- title: título claro em português
- category: uma de técnica, comercial, financeira, escalação (minúsculas, sem acentos extras onde possível seguindo típico YAML)
  Use exatamente: técnica, comercial, financeira, ou escalação (com ç em escalação)
- tags: lista YAML entre colchetes, 4 a 8 tags curtas em minúsculas com hífens se necessário
- module: módulo lógico (ex.: financeiro, billing, onboarding, técnico-geral)
- audience: interno
- created_at: data de hoje no formato YYYY-MM-DD
- updated_at: igual created_at neste primeiro rascunho
- author: "Customer Success Copilot"

Corpo sugerido (seções markdown):
1. Título nível # repetindo ou refinando title
2. ## Contexto típico
3. ## Como finalizar o ticket (passo a passo para o analista)
4. ## Verificações e evidências solicitadas ao cliente (se aplicável)
5. ## Critérios de encerramento
6. ## Escalação (quando escalar e para quem)
7. ## Tickets relacionados (placeholder: referenciar o id do ticket de origem)

Não invente números de incidente reais. Não inclua dados pessoais além do necessário.
Responda SOMENTE com o conteúdo completo do arquivo Markdown (frontmatter + corpo). Sem introdução antes do primeiro ---.
"""


def _build_user_payload(state: WorkflowState) -> dict:
    triage_payload = None
    if state.triage:
        triage_payload = asdict(state.triage)

    texto_aprovado = state.draft
    if state.hil_decision == "corrigir" and state.hil_correction:
        texto_aprovado = f"{state.draft}\n\n--- Correção do analista ---\n{state.hil_correction}"

    return {
        "ticket": dict(state.ticket),
        "triage": triage_payload,
        "classification_error": state.classification_error,
        "especialista": state.specialist,
        "rascunho_aprovado": texto_aprovado,
        "citacoes_resumo": state.citations[:12] if state.citations else [],
    }


def generate_kb_article(state: WorkflowState, *, logger: JsonlLogger, model: str = "gpt-4o-mini") -> str:
    with StepTimer(logger, "kb_generator"):
        llm = ChatOpenAI(model=model, temperature=0.2)
        payload = _build_user_payload(state)
        raw = llm.invoke(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        ).content

        text = raw.strip()
        if not text.startswith("---"):
            fence = re.search(r"```(?:markdown)?\s*([\s\S]*?)\s*```", text)
            if fence:
                text = fence.group(1).strip()

        if not text.startswith("---"):
            raise ValueError("Resposta do gerador de KB não começa com frontmatter ---")

        logger.log("kb_article_generated", chars=len(text), ticket_id=state.ticket["id"])
        return text
