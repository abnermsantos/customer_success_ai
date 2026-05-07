from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from customer_success_ai.mcp_backend.client import call_tool as mcp_call_tool


@dataclass(frozen=True)
class KbDoc:
    doc_id: str
    title: str
    category: str
    tags: list[str]
    module: str | None
    source_path: str
    content: str


def fetch_kb_search(
    url: str,
    *,
    category: str,
    q: str = "",
    limit: int = 8,
    timeout: float = 60.0,
) -> list[KbDoc]:
    """GET JSON: lista de KB docs (dicts) retornada por /kb/search."""
    _ = url  # Mantido por compatibilidade com chamadas atuais; MCP é o único caminho.
    data = mcp_call_tool(
        "kb.search",
        {
            "category": category,
            "q": q,
            "limit": int(limit),
            "timeout": float(timeout),
        },
    )
    docs_raw = (data or {}).get("docs", [])
    docs: list[KbDoc] = []
    for x in docs_raw:
        if not isinstance(x, dict):
            continue
        docs.append(
            KbDoc(
                doc_id=str(x.get("doc_id") or ""),
                title=str(x.get("title") or ""),
                category=str(x.get("category") or ""),
                tags=list(x.get("tags") or []),
                module=x.get("module"),
                source_path=str(x.get("source_path") or ""),
                content=str(x.get("content") or ""),
            )
        )
    return docs


def create_kb_doc(url: str, *, markdown: str, timeout: float = 60.0) -> dict[str, Any]:
    """POST JSON para /kb/docs para persistir um novo arquivo .md."""
    _ = url  # Mantido por compatibilidade com chamadas atuais; MCP é o único caminho.
    data = mcp_call_tool(
        "kb.create_doc",
        {
            "markdown": markdown,
            "timeout": float(timeout),
        },
    )
    if not isinstance(data, dict):
        raise ValueError("KB create (via MCP): resposta deve ser um objeto JSON")
    return data


def fetch_tickets_history(url: str, *, timeout: float = 60.0) -> list[dict[str, Any]]:
    """GET JSON: corpo deve ser a mesma lista de objetos que o arquivo mock (array na raiz)."""
    _ = url  # Mantido por compatibilidade com chamadas atuais; MCP é o único caminho.
    data = mcp_call_tool("tickets.history", {"timeout": float(timeout)})
    tickets = (data or {}).get("tickets", [])
    if not isinstance(tickets, list):
        raise ValueError("Histórico (via MCP): resposta deve conter tickets: array")
    return [x for x in tickets if isinstance(x, dict)]


def tickets_historico_loader(historico_url: str) -> Callable[[], list[dict[str, Any]]]:
    u = historico_url.strip()

    def _from_api() -> list[dict[str, Any]]:
        try:
            return fetch_tickets_history(u)
        except Exception as e:
            raise RuntimeError(f"Falha ao obter histórico de tickets via MCP (url={u!r}): {e}") from e

    return _from_api

