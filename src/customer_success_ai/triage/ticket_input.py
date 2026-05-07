from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from customer_success_ai.workflow.state import Ticket


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ticket_from_client_input(nome_cliente: str, descricao: str) -> Ticket:
    """Monta um ticket mínimo a partir da entrada humana (nome + problema).

    IDs são derivados de forma determinística/levemente aleatória; a triagem
    deve preencher título adequado, ``tipo`` (categoria) e ``prioridade`` (via urgência).
    """
    cliente = nome_cliente.strip()
    body = descricao.strip()
    if not cliente:
        raise ValueError("nome do cliente não pode ser vazio")
    if not body:
        raise ValueError("descrição do problema não pode ser vazia")

    slug = hashlib.sha256(cliente.lower().encode()).hexdigest()[:8].upper()
    now = _utc_now_iso()
    preview = body.split("\n", 1)[0].strip()
    titulo_provisório = preview[:120] + ("…" if len(preview) > 120 else "")
    return {
        "id": f"TKT-{uuid.uuid4().hex[:8].upper()}",
        "titulo": titulo_provisório or "Solicitação do cliente",
        "descricao": body,
        "tipo": "triagem_pendente",
        "status": "aberto",
        "prioridade": "indefinida",
        "responsavel": "",
        "id_cliente": f"CLI-{slug}", # TODO: Alterar para o id do cliente real
        "nome_cliente": cliente,
        "criado_em": now,
        "atualizado_em": now,
    }
