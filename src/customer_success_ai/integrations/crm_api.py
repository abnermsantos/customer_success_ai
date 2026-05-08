"""Contrato HTTP do CRM (mock): base em /crm; endpoints fixos aqui."""

from __future__ import annotations


CLIENTES = "clientes"


def normalize_api_base(raw: str) -> str:
    return raw.strip().rstrip("/")


def endpoint_url(base: str, resource: str) -> str:
    b = normalize_api_base(base)
    r = resource.strip().lstrip("/")
    return f"{b}/{r}"


def clientes_url(base: str) -> str:
    """Endpoint para buscar cliente por nome via querystring (?nome=...)."""
    return endpoint_url(base, CLIENTES)


def health_url(base: str) -> str:
    return endpoint_url(base, "health")

