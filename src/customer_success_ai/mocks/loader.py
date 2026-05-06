from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


@dataclass(frozen=True)
class KbDoc:
    doc_id: str
    title: str
    category: str
    tags: list[str]
    module: str | None
    source_path: str
    content: str


def _parse_frontmatter_markdown(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    _, fm_raw, body = parts[0], parts[1], parts[2]
    meta = yaml.safe_load(fm_raw) or {}
    return meta, body.lstrip("\n")


def load_kb_docs(kb_dir: Path) -> list[KbDoc]:
    docs: list[KbDoc] = []
    for p in sorted(kb_dir.glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter_markdown(raw)
        docs.append(
            KbDoc(
                doc_id=str(meta.get("id") or p.stem),
                title=str(meta.get("title") or p.stem),
                category=str(meta.get("category") or ""),
                tags=list(meta.get("tags") or []),
                module=meta.get("module"),
                source_path=str(p.as_posix()),
                content=body,
            )
        )
    return docs


def fetch_tickets_history(url: str, *, timeout: float = 60.0) -> list[dict[str, Any]]:
    """GET JSON: corpo deve ser a mesma lista de objetos que o arquivo mock (array na raiz)."""
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Histórico de tickets: resposta JSON deve ser um array na raiz")
    return [x for x in data if isinstance(x, dict)]


def tickets_historico_loader(historico_url: str) -> Callable[[], list[dict[str, Any]]]:
    u = historico_url.strip()

    def _from_api() -> list[dict[str, Any]]:
        try:
            return fetch_tickets_history(u)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"Falha ao obter histórico de tickets em {u!r}: {e}") from e

    return _from_api

