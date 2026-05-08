from __future__ import annotations

import logging
import sys
from pathlib import Path
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
import uvicorn
import yaml

from customer_success_ai.integrations.http_backend import create_kb_doc as http_create_kb_doc
from customer_success_ai.integrations.http_backend import fetch_crm_customer_by_name as http_fetch_crm_customer_by_name
from customer_success_ai.integrations.http_backend import fetch_kb_search as http_fetch_kb_search
from customer_success_ai.integrations.http_backend import fetch_open_tickets_count as http_fetch_open_tickets_count
from customer_success_ai.integrations.http_backend import fetch_tickets_history as http_fetch_tickets_history
from customer_success_ai.integrations.crm_api import clientes_url as crm_clientes_url
from customer_success_ai.integrations.kb_api import create_doc_url as kb_create_doc_url
from customer_success_ai.integrations.kb_api import normalize_api_base as normalize_kb_base
from customer_success_ai.integrations.kb_api import search_url as kb_search_url
from customer_success_ai.integrations.tickets_api import health_url, historico_url, normalize_api_base, open_count_url
from customer_success_ai.observability import mcp_server_log_path


@dataclass(frozen=True)
class McpBackendConfig:
    tickets_api_base: str
    tickets_historico_url: str
    tickets_health_url: str
    tickets_open_count_url: str
    kb_api_base: str
    kb_search_url: str
    kb_create_url: str
    crm_api_base: str
    crm_clientes_url: str


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

    u = urlparse(base)
    crm_base = f"{u.scheme}://{u.netloc}/crm"

    return McpBackendConfig(
        tickets_api_base=base,
        tickets_historico_url=historico_url(base),
        tickets_health_url=health_url(base),
        tickets_open_count_url=open_count_url(base),
        kb_api_base=kb_base,
        kb_search_url=kb_search_url(kb_base),
        kb_create_url=kb_create_doc_url(kb_base),
        crm_api_base=crm_base,
        crm_clientes_url=crm_clientes_url(crm_base),
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

    def _validate_kb_article(markdown: str) -> dict[str, Any]:
        errors: list[str] = []
        md = (markdown or "").strip()

        if not md.startswith("---"):
            return {
                "ok": False,
                "errors": ["markdown deve começar com frontmatter '---'"],
                "frontmatter": {},
                "extracted": {},
            }

        parts = md.split("---", 2)
        if len(parts) < 3:
            return {
                "ok": False,
                "errors": ["frontmatter incompleto: esperado '--- ... ---'"],
                "frontmatter": {},
                "extracted": {},
            }

        fm_raw = parts[1]
        try:
            fm = yaml.safe_load(fm_raw) or {}
        except Exception as e:
            return {
                "ok": False,
                "errors": [f"frontmatter YAML inválido: {e}"],
                "frontmatter": {},
                "extracted": {},
            }

        if not isinstance(fm, dict):
            return {
                "ok": False,
                "errors": ["frontmatter deve ser um objeto YAML (map/dict)"],
                "frontmatter": {},
                "extracted": {},
            }

        # Campos obrigatórios do padrão atual
        required = ["id", "title", "category", "tags", "module", "audience", "created_at", "updated_at", "author"]
        for k in required:
            if k not in fm or fm.get(k) in (None, "", []):
                errors.append(f"frontmatter sem campo obrigatório: {k}")

        allowed_categories = {"técnica", "comercial", "financeira", "escalação"}
        category = fm.get("category")
        if isinstance(category, str):
            if category.strip() not in allowed_categories:
                errors.append(f"category inválida: {category!r} (permitidas: {sorted(allowed_categories)})")
        elif category is not None:
            errors.append("category deve ser string")

        tags = fm.get("tags")
        if isinstance(tags, list):
            if not (4 <= len(tags) <= 8):
                errors.append("tags deve ter entre 4 e 8 itens")
        elif tags is not None:
            errors.append("tags deve ser lista YAML (ex.: [a, b, c])")

        audience = fm.get("audience")
        if audience is not None and str(audience).strip() != "interno":
            errors.append("audience deve ser 'interno'")

        # Datas no formato YYYY-MM-DD
        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        created_at = fm.get("created_at")
        updated_at = fm.get("updated_at")
        for label, v in (("created_at", created_at), ("updated_at", updated_at)):
            if v is None:
                continue
            s = str(v).strip()
            if not date_re.match(s):
                errors.append(f"{label} deve estar no formato YYYY-MM-DD (recebido: {s!r})")

        # Extração útil (sem forçar normalização ainda)
        extracted = {
            "id": str(fm.get("id") or "").strip(),
            "title": str(fm.get("title") or "").strip(),
            "category": str(fm.get("category") or "").strip(),
            "module": str(fm.get("module") or "").strip(),
            "tags_count": len(tags) if isinstance(tags, list) else 0,
        }

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "frontmatter": fm,
            "extracted": extracted,
        }

    # -------- tickets.* --------
    @mcp.tool(name="tickets.history")
    def tickets_history(
        *,
        tipo: str | None = None,
        status: str | None = None,
        customer_id: str | None = None,
        limit: int | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Retorna histórico de tickets com filtros mecânicos opcionais."""
        history = http_fetch_tickets_history(
            cfg.tickets_historico_url,
            timeout=timeout,
            tipo=tipo,
            status=status,
            customer_id=customer_id,
            limit=limit,
        )
        return {"tickets": history, "count": len(history)}

    @mcp.tool(name="tickets.open_count")
    def tickets_open_count(customer_id: str, timeout: float = 30.0) -> dict[str, Any]:
        """Retorna a contagem de tickets vivos para um id_cliente."""
        open_count = http_fetch_open_tickets_count(cfg.tickets_open_count_url, customer_id=customer_id, timeout=timeout)
        return {"customer_id": customer_id, "open_count": open_count}

    # -------- kb.* --------
    @mcp.tool(name="kb.search")
    def kb_search(category: str, q: str = "", limit: int = 8, timeout: float = 60.0) -> dict[str, Any]:
        """Busca KB via /kb/search do backend HTTP atual."""
        docs = http_fetch_kb_search(cfg.kb_search_url, category=category, q=q, limit=limit, timeout=timeout)
        return {"docs": [d.__dict__ for d in docs], "count": len(docs)}

    @mcp.tool(name="kb.validate_article")
    def kb_validate_article(markdown: str) -> dict[str, Any]:
        """
        Validação determinística (sem LLM) do artigo de KB.

        Uso esperado:
        1) o agente gera `markdown`
        2) chama kb.validate_article para obter erros estruturados
        3) corrige e só então chama kb.create_doc
        """
        return _validate_kb_article(markdown)

    @mcp.tool(name="kb.create_doc")
    def kb_create_doc(markdown: str, timeout: float = 60.0) -> dict[str, Any]:
        """
        Persiste um doc na KB via /kb/docs do backend HTTP atual.

        Nota: guardrails (HIL/permissions) serão aplicados na etapa de tools/orquestração.
        """
        validation = _validate_kb_article(markdown)
        if not validation.get("ok"):
            errors = validation.get("errors") or []
            msg = "artigo KB inválido; corrija antes de salvar"
            if isinstance(errors, list) and errors:
                msg += ": " + "; ".join(map(str, errors[:8]))
            raise ValueError(msg)
        out = http_create_kb_doc(cfg.kb_create_url, markdown=markdown, timeout=timeout)
        return out

    # -------- crm.* --------
    @mcp.tool(name="crm.get_customer_by_name")
    def crm_get_customer_by_name(name: str, timeout: float = 30.0) -> dict[str, Any]:
        """Busca o cliente no CRM (mock/real) pelo nome."""
        cust = http_fetch_crm_customer_by_name(cfg.crm_clientes_url, name=name, timeout=timeout)
        return {"found": cust is not None, "customer": cust}

    return mcp

def normalize_base_for_parse(base: str) -> str:
    """Garante netloc parseável quando o usuário informa só path (evitar edge cases)."""
    if not base:
        base = "127.0.0.1:8005"
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

def _uvicorn_file_log_config(log_path: Path) -> dict[str, Any]:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, level_name, logging.INFO)
    level_label = logging.getLevelName(log_level)
    fname = str(log_path.resolve())

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    fmt_access = '%(asctime)s | %(levelname)s | %(name)s | %(client_addr)s - "%(request_line)s" %(status_code)s'

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": fmt},
            "access": {"format": fmt_access},
        },
        "handlers": {
            "default": {
                "class": "logging.FileHandler",
                "formatter": "default",
                "filename": fname,
                "encoding": "utf-8",
                "mode": "a",
            },
            "access": {
                "class": "logging.FileHandler",
                "formatter": "access",
                "filename": fname,
                "encoding": "utf-8",
                "mode": "a",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level_label, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level_label, "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": level_label, "propagate": False},
        },
        "root": {"handlers": ["default"], "level": level_label},
    }


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

    log_path = mcp_server_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_cfg = _uvicorn_file_log_config(log_path)

    stdio_sink = log_path.open("a", encoding="utf-8")
    if os.getenv("MCP_QUIET_LAUNCHER") != "1":
        print(f"[MCP] Logs do servidor neste arquivo: {log_path.resolve()}", file=sys.__stderr__)
    sys.stdout = stdio_sink
    sys.stderr = stdio_sink

    mcp = build_mcp_server()
    uvicorn.run(
        mcp.streamable_http_app(),
        host=host,
        port=port,
        log_config=log_cfg,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=True,
        use_colors=False,
    )


if __name__ == "__main__":
    main()

