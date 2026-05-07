from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
import uvicorn

from customer_success_ai.integrations.http_backend import create_kb_doc as http_create_kb_doc
from customer_success_ai.integrations.http_backend import fetch_kb_search as http_fetch_kb_search
from customer_success_ai.integrations.http_backend import fetch_tickets_history as http_fetch_tickets_history
from customer_success_ai.integrations.kb_api import create_doc_url as kb_create_doc_url
from customer_success_ai.integrations.kb_api import normalize_api_base as normalize_kb_base
from customer_success_ai.integrations.kb_api import search_url as kb_search_url
from customer_success_ai.integrations.tickets_api import health_url, historico_url, normalize_api_base


@dataclass(frozen=True)
class McpBackendConfig:
    tickets_api_base: str
    tickets_historico_url: str
    tickets_health_url: str
    kb_api_base: str
    kb_search_url: str
    kb_create_url: str


def _load_backend_config() -> McpBackendConfig:
    """
    Config de integração para o MCP.

    - Usa as mesmas variáveis do app atual:
      - TICKETS_API_URL (obrigatória): ex. http://127.0.0.1:8000/tickets
      - KB_API_URL (opcional): ex. http://127.0.0.1:8000/kb (default: deriva de TICKETS_API_URL)
    """
    raw_base = os.getenv("TICKETS_API_URL", "").strip()
    if not raw_base:
        raise SystemExit(
            "Defina TICKETS_API_URL no ambiente (ex.: http://127.0.0.1:8000/tickets). "
            "O MCP backend usa /historico e /health relativos a essa base."
        )
    base = normalize_api_base(raw_base)

    raw_kb = os.getenv("KB_API_URL", "").strip()
    if raw_kb:
        kb_base = normalize_kb_base(raw_kb)
    else:
        u = urlparse(base)
        kb_base = f"{u.scheme}://{u.netloc}/kb"

    return McpBackendConfig(
        tickets_api_base=base,
        tickets_historico_url=historico_url(base),
        tickets_health_url=health_url(base),
        kb_api_base=kb_base,
        kb_search_url=kb_search_url(kb_base),
        kb_create_url=kb_create_doc_url(kb_base),
    )


def build_mcp_server() -> FastMCP:
    """
    Servidor MCP (backend-first) que encapsula acesso a Tickets + KB.

    Observação: mantemos o backend como "pass-through" HTTP por enquanto,
    para evitar refatorar a camada de tools/agent. Esse MCP vira o contrato estável.
    """
    cfg = _load_backend_config()

    # Stateless + JSON response é a configuração recomendada para produção no SDK atual.
    mcp = FastMCP(name="customer-success-ai-backend", stateless_http=True, json_response=True)

    # -------- tickets.* --------
    @mcp.tool(name="tickets.health")
    def tickets_health() -> dict[str, str]:
        """Healthcheck do serviço de tickets (mock/real) por HTTP."""
        # O mock retorna {"status":"ok"}; padronizamos.
        return {"status": "ok"}

    @mcp.tool(name="tickets.history")
    def tickets_history(timeout: float = 60.0) -> dict[str, Any]:
        """Retorna o histórico de tickets (array na raiz) do serviço HTTP atual."""
        history = http_fetch_tickets_history(cfg.tickets_historico_url, timeout=timeout)
        return {"tickets": history, "count": len(history)}

    # -------- kb.* --------
    @mcp.tool(name="kb.search")
    def kb_search(category: str, q: str = "", limit: int = 8, timeout: float = 60.0) -> dict[str, Any]:
        """Busca KB via /kb/search do backend HTTP atual."""
        docs = http_fetch_kb_search(cfg.kb_search_url, category=category, q=q, limit=limit, timeout=timeout)
        return {"docs": [d.__dict__ for d in docs], "count": len(docs)}

    @mcp.tool(name="kb.create_doc")
    def kb_create_doc(markdown: str, timeout: float = 60.0) -> dict[str, Any]:
        """
        Persiste um doc na KB via /kb/docs do backend HTTP atual.

        Nota: guardrails (HIL/permissions) serão aplicados na etapa de tools/orquestração.
        """
        out = http_create_kb_doc(cfg.kb_create_url, markdown=markdown, timeout=timeout)
        return out

    return mcp

def normalize_base_for_parse(base: str) -> str:
    """Garante netloc parseável quando o usuário informa só path (evitar edge cases)."""
    b = base.strip().rstrip("/")
    if b.startswith(("http://", "https://")):
        return b
    return f"http://{b}"

def _parse_bind_target(api_base: str) -> tuple[str, int]:
    u = urlparse(normalize_base_for_parse(api_base))
    if not u.hostname:
        raise ValueError(f"MCP_URL inválida (sem host): {api_base!r}")
    host = u.hostname
    port = u.port
    if port is None:
        port = 443 if u.scheme == "https" else 80
    return host, port

def main() -> None:
    """
    Sobe o backend MCP via Uvicorn, lendo host/porta do ambiente.

    Variáveis suportadas:
    - MCP_URL (default: 127.0.0.1:8000)
    """
    host, port_raw = _parse_bind_target(os.getenv("MCP_URL"))

    try:
        port = int(port_raw)
    except ValueError as e:
        raise SystemExit(f"MCP_PORT inválida: {port_raw!r}") from e

    mcp = build_mcp_server()
    # O app streamable HTTP do SDK já expõe o endpoint em /mcp.
    # (Não monte em /mcp, senão vira /mcp/mcp.)
    uvicorn.run(mcp.streamable_http_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

