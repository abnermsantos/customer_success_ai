from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _mcp_url() -> str | None:
    return (os.getenv("MCP_URL") or "").strip() or None


async def _call_tool_async(url: str, name: str, arguments: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(headers={"Accept": "application/json"}) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                res = await session.call_tool(name, arguments=arguments or {})
                # Prefer structured content when available (JSON-native).
                if res.structuredContent is not None:
                    return res.structuredContent

                # Fallback: concat text blocks.
                texts: list[str] = []
                for c in res.content:
                    t = getattr(c, "text", None)
                    if isinstance(t, str):
                        texts.append(t)
                return "\n".join(texts).strip()


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """
    Chamador síncrono para tools MCP via Streamable HTTP.

    Este wrapper existe para manter o restante do código (atualmente síncrono)
    sem refatoração para async. Para cargas maiores, vamos querer sessão reutilizada.
    """
    url = _mcp_url()
    if not url:
        raise RuntimeError("MCP_URL não definido no ambiente (ex.: http://127.0.0.1:8001/mcp)")
    return asyncio.run(_call_tool_async(url, name, arguments))


def is_enabled() -> bool:
    return _mcp_url() is not None

