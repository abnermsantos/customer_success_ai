from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse
import yaml

# mocks/ fica na raíz do repo; este arquivo está em src/app_mock/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_JSON = _REPO_ROOT / "mocks" / "tickets" / "tickets_historico_mock.json"
_DEFAULT_KB_DIR = _REPO_ROOT / "mocks" / "base_conhecimento"

tickets = APIRouter(prefix="/tickets", tags=["tickets"])
kb = APIRouter(prefix="/kb", tags=["kb"])


def _payload_path() -> Path:
    return Path(os.environ.get("TICKETS_MOCK_JSON", str(_DEFAULT_JSON)))

def _kb_dir() -> Path:
    return Path(os.environ.get("KB_MOCK_DIR", str(_DEFAULT_KB_DIR)))

def _parse_frontmatter_markdown(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    _, fm_raw, body = parts[0], parts[1], parts[2]
    meta = yaml.safe_load(fm_raw) or {}
    return meta, body.lstrip("\n")

def _safe_slug(raw: str) -> str:
    s = (raw or "").strip()
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "_", ".", "+"):
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out).strip("-")
    return slug


@tickets.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@tickets.get("/historico")
def tickets_historico() -> JSONResponse:
    """Corpo idêntico ao JSON de mock: array de tickets na raiz."""
    p = _payload_path()
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"Arquivo não encontrado: {p}")
    raw = p.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON inválido em {p}: {e}") from e
    if not isinstance(data, list):
        raise HTTPException(status_code=500, detail="O arquivo deve ser um JSON array na raiz")
    return JSONResponse(content=data)

@kb.get("/health")
def kb_health() -> dict[str, str]:
    return {"status": "ok"}


@kb.get("/search")
def kb_search(category: str = "", q: str = "", limit: int = 8) -> JSONResponse:
    """Busca simples (mock) nos arquivos .md da KB.

    - category: filtra pelo frontmatter `category` (ex.: financeira, técnica, comercial, escalação)
    - q: filtro opcional por substring (case-insensitive) em título/conteúdo/tags
    """
    cn = (category or "").strip().lower()
    qn = (q or "").strip().lower()
    lim = max(1, min(int(limit), 50))
    base = _kb_dir()
    if not base.is_dir():
        raise HTTPException(status_code=404, detail=f"Diretório KB não encontrado: {base}")

    results: list[dict] = []
    for p in sorted(base.glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter_markdown(raw)
        meta_cat = str(meta.get("category") or "").strip().lower()
        if cn and meta_cat != cn:
            continue
        title = str(meta.get("title") or p.stem)
        tags = list(meta.get("tags") or [])
        hay = f"{title}\n{body}\n{' '.join(map(str, tags))}".lower()
        if qn and qn not in hay:
            continue
        results.append(
            {
                "doc_id": str(meta.get("id") or p.stem),
                "title": title,
                "category": str(meta.get("category") or ""),
                "tags": tags,
                "module": meta.get("module"),
                "source_path": str(p.as_posix()),
                "content": body,
            }
        )
        if len(results) >= lim:
            break
    return JSONResponse(content=results)


@kb.post("/docs")
def kb_create_doc(payload: dict = Body(...)) -> JSONResponse:
    """Cria um novo arquivo .md na pasta de mocks da KB."""
    md = str(payload.get("markdown") or "")
    if not md.strip():
        raise HTTPException(status_code=400, detail="Campo obrigatório: markdown")

    meta, _ = _parse_frontmatter_markdown(md)
    doc_id = str(meta.get("id") or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="Frontmatter sem 'id' (use id: ...)")
    slug = _safe_slug(doc_id)
    if not slug:
        raise HTTPException(status_code=400, detail="id inválido para nome de arquivo")

    base = _kb_dir()
    base.mkdir(parents=True, exist_ok=True)

    # Evita sobrescrever: se existir, cria sufixo -N.
    candidate = base / f"{slug}.md"
    if candidate.exists():
        i = 2
        while True:
            cand = base / f"{slug}-{i}.md"
            if not cand.exists():
                candidate = cand
                break
            i += 1

    candidate.write_text(md, encoding="utf-8")
    return JSONResponse(
        content={
            "status": "created",
            "doc_id": doc_id,
            "path": str(candidate.as_posix()),
        }
    )


app = FastAPI(title="Tickets — mock API", version="0.1.0")
app.include_router(tickets)
app.include_router(kb)
