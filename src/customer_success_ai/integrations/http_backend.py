from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from urllib.parse import urlencode


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
    params = urlencode({"category": category, "q": q, "limit": str(limit)})
    full = f"{url.rstrip('/')}" + ("" if "?" in url else f"?{params}")
    req = Request(full, headers={"Accept": "application/json"}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("KB search: resposta JSON deve ser um array na raiz")

    docs: list[KbDoc] = []
    for x in data:
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
    payload = {"markdown": markdown}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url.strip(),
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("KB create: resposta JSON deve ser um objeto")
    return data


def fetch_tickets_history(url: str, *, timeout: float = 60.0) -> list[dict[str, Any]]:
    """GET JSON: corpo deve ser um array na raiz."""
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Histórico de tickets: resposta JSON deve ser um array na raiz")
    return [x for x in data if isinstance(x, dict)]


def fetch_crm_customer_by_name(url: str, *, name: str, timeout: float = 30.0) -> dict[str, Any] | None:
    """GET JSON: retorna dict do cliente, ou None em caso de 404."""
    q = (name or "").strip()
    if not q:
        raise ValueError("CRM: name não pode ser vazio")

    full = f"{url.rstrip('/')}" + ("" if "?" in url else f"?{urlencode({'nome': q})}")
    req = Request(full, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001 - compat com URLError/HTTPError sem importar
        # HTTPError em urllib expõe .code; tratamos 404 como "não encontrado".
        code = getattr(e, "code", None)
        if code == 404:
            return None
        raise

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("CRM: resposta JSON deve ser um objeto")
    return data

