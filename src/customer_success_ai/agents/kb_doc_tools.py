from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from customer_success_ai.mcp_backend.client import call_tool as mcp_call_tool


@tool("kb_validate_article")
def kb_validate_article(markdown: str) -> dict[str, Any]:
    """Valida determinísticamente um artigo de KB (frontmatter + regras)."""
    out = mcp_call_tool("kb.validate_article", {"markdown": markdown})
    if not isinstance(out, dict):
        raise ValueError("kb.validate_article: resposta MCP deve ser um objeto JSON")
    return out


@tool("kb_create_doc")
def kb_create_doc(markdown: str, timeout: float = 60.0) -> dict[str, Any]:
    """Persiste um artigo de KB (side-effect)."""
    out = mcp_call_tool("kb.create_doc", {"markdown": markdown, "timeout": float(timeout)})
    if isinstance(out, str):
        raise ValueError(out)
    if not isinstance(out, dict):
        raise ValueError("kb.create_doc: resposta MCP deve ser um objeto JSON")
    return out

