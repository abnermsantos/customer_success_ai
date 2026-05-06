from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse

# mocks/ fica na raíz do repo; este arquivo está em src/app_mock/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_JSON = _REPO_ROOT / "mocks" / "tickets" / "tickets_historico_mock.json"

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _payload_path() -> Path:
    return Path(os.environ.get("TICKETS_MOCK_JSON", str(_DEFAULT_JSON)))


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/historico")
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


app = FastAPI(title="Tickets — mock API", version="0.1.0")
app.include_router(router)
