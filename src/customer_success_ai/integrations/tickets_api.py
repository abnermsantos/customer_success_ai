"""Contrato HTTP dos tickets: base em TICKETS_API_URL; caminhos de recurso fixos aqui."""

from __future__ import annotations

# Recursos relativos à base (ex.: http://localhost:8000/tickets → …/historico)
HISTORICO = "historico"


def normalize_api_base(raw: str) -> str:
    return raw.strip().rstrip("/")


def endpoint_url(base: str, resource: str) -> str:
    b = normalize_api_base(base)
    r = resource.strip().lstrip("/")
    return f"{b}/{r}"


def historico_url(base: str) -> str:
    return endpoint_url(base, HISTORICO)


def health_url(base: str) -> str:
    return endpoint_url(base, "health")
