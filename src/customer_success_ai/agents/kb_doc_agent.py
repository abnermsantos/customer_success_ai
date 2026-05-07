from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import Annotated

from customer_success_ai.agents.kb_doc_tools import kb_validate_article, kb_create_doc
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.workflow.state import WorkflowState


SYSTEM = """Você é o agente de Documentação da Base de Conhecimento interna.
Você vai produzir UM único arquivo Markdown no padrão da empresa:
- Começar com frontmatter YAML (--- ... ---)
- Depois corpo em Markdown

Obrigatório no frontmatter:
- id, title, category, tags, module, audience, created_at, updated_at, author

Regras:
- Não invente dados factuais. Se algo não estiver no contexto, use placeholders e peça evidências.
- Responda com APENAS o arquivo Markdown completo (frontmatter + corpo), sem texto fora do Markdown.
- Antes de finalizar, valide o Markdown chamando a ferramenta kb_validate_article.
  Se retornar ok=false, corrija e valide novamente.
"""


def _build_user_payload(state: WorkflowState) -> dict[str, Any]:
    triage_payload = asdict(state.triage) if state.triage else None
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


def _extract_markdown(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("---"):
        return text
    fence = re.search(r"```(?:markdown)?\s*([\s\S]*?)\s*```", text)
    if fence:
        return fence.group(1).strip()
    return text


class KBMessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class KBPublishState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _kb_should_finish(state: KBMessagesState) -> Literal["tools", "finalize", "llm"]:
    """
    Roteamento:
    - se a última mensagem pede tools -> tools
    - se a última mensagem é AI sem tool_calls -> finalize
    """
    cond = tools_condition(state)
    if cond == "tools":
        return "tools"
    return "finalize"


def generate_kb_article_with_tools(
    state: WorkflowState,
    *,
    logger: JsonlLogger,
    model: str = "gpt-4o-mini",
    max_tool_roundtrips: int = 8,
) -> str:
    """
    Gera o artigo KB permitindo tool-calling para validação determinística.
    """
    with StepTimer(logger, "kb_generator_tools"):
        llm = ChatOpenAI(model=model, temperature=0.2).bind_tools([kb_validate_article])
        payload = _build_user_payload(state)
        initial: KBMessagesState = {
            "messages": [
                SystemMessage(content=SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ]
        }

        def llm_node(s: KBMessagesState) -> KBMessagesState:
            ai = llm.invoke(s["messages"])
            return {"messages": [ai]}

        tool_node = ToolNode([kb_validate_article])

        def finalize_node(s: KBMessagesState) -> KBMessagesState:
            """
            Garante que houve validação ok antes de encerrar.
            Se não houver, força o modelo a chamar kb_validate_article.
            """
            messages = s["messages"]
            last = messages[-1]
            md = _extract_markdown(str(getattr(last, "content", "") or ""))

            # Procura o último ToolMessage do validate com ok=true.
            ok = False
            for m in reversed(messages):
                if getattr(m, "type", None) == "tool":
                    try:
                        payload = json.loads(getattr(m, "content", "") or "{}")
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict) and payload.get("ok") is True:
                        ok = True
                        break

            if not ok:
                # Sem fallback de tool: apenas exige que o modelo valide.
                messages = messages + [
                    HumanMessage(
                        content=(
                            "Antes de finalizar, você DEVE chamar kb_validate_article com o markdown completo. "
                            "Depois, se ok=true, devolva o markdown final."
                        )
                    )
                ]
                return {"messages": messages}

            # Validado: manter última AI como resposta final.
            logger.log("kb_article_generated", chars=len(md), ticket_id=state.ticket["id"])
            return {"messages": messages}

        g = StateGraph(KBMessagesState)
        g.add_node("llm", llm_node)
        g.add_node("tools", tool_node)
        g.add_node("finalize", finalize_node)
        g.set_entry_point("llm")
        g.add_conditional_edges("llm", _kb_should_finish, {"tools": "tools", "finalize": "finalize", "llm": "llm"})
        g.add_edge("tools", "llm")
        # finalize: ou termina ou volta pro llm se faltou validação
        def _route_after_finalize(s: KBMessagesState) -> str:
            last = s["messages"][-1]
            # Se finalize adicionou uma HumanMessage exigindo validação, volta pro llm
            if getattr(last, "type", None) == "human":
                return "llm"
            return END

        g.add_conditional_edges("finalize", _route_after_finalize, {"llm": "llm", END: END})

        out = g.compile().invoke(initial, {"recursion_limit": max_tool_roundtrips * 3})
        final_msg = out["messages"][-1]
        md = _extract_markdown(str(getattr(final_msg, "content", "") or ""))
        if not md.startswith("---"):
            raise RuntimeError("Agente não retornou um markdown com frontmatter.")
        return md


def publish_kb_article_with_tools(
    markdown: str,
    *,
    logger: JsonlLogger,
    model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """
    Publica o artigo chamando kb.create_doc via tool-calling.
    Deve ser usado somente após aprovação humana.
    """
    with StepTimer(logger, "kb_publish_tools"):
        llm = ChatOpenAI(model=model, temperature=0).bind_tools([kb_create_doc])

        initial: KBPublishState = {
            "messages": [
                SystemMessage(
                    content=(
                        "Você é um publicador de KB. Você DEVE chamar a ferramenta kb_create_doc "
                        "com o markdown fornecido. Depois, responda somente com um JSON curto "
                        "contendo status/doc_id/path."
                    )
                ),
                HumanMessage(content=markdown),
            ]
        }

        def llm_node(s: KBPublishState) -> KBPublishState:
            ai = llm.invoke(s["messages"])
            return {"messages": [ai]}

        tool_node = ToolNode([kb_create_doc])

        def finalize_node(s: KBPublishState) -> KBPublishState:
            """
            Exige que a publicação tenha acontecido (ToolMessage com status=created).
            Se ainda não ocorreu, pede explicitamente para chamar a tool.
            """
            for m in reversed(s["messages"]):
                if getattr(m, "type", None) == "tool":
                    try:
                        payload = json.loads(getattr(m, "content", "") or "{}")
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict) and payload.get("status") == "created":
                        logger.log("kb_persisted", **payload)
                        return {"messages": s["messages"]}

            return {
                "messages": [
                    HumanMessage(
                        content=(
                            "A publicação ainda não foi feita. "
                            "Chame kb_create_doc com o markdown completo para persistir."
                        )
                    )
                ]
            }

        g = StateGraph(KBPublishState)
        g.add_node("llm", llm_node)
        g.add_node("tools", tool_node)
        g.add_node("finalize", finalize_node)
        g.set_entry_point("llm")
        g.add_conditional_edges("llm", tools_condition, {"tools": "tools", "__end__": "finalize"})
        g.add_edge("tools", "finalize")

        def _route_after_finalize(s: KBPublishState) -> str:
            last = s["messages"][-1]
            if getattr(last, "type", None) == "human":
                return "llm"
            return END

        g.add_conditional_edges("finalize", _route_after_finalize, {"llm": "llm", END: END})

        out = g.compile().invoke(initial, {"recursion_limit": 12})
        for m in reversed(out["messages"]):
            if getattr(m, "type", None) == "tool":
                try:
                    payload = json.loads(getattr(m, "content", "") or "{}")
                except Exception:
                    payload = {}
                if isinstance(payload, dict) and payload.get("status") == "created":
                    return payload
        raise RuntimeError("Publicação KB falhou: kb_create_doc não retornou status=created.")

