"""Contrato HTTP da KB: base (KB_API_URL) e endpoints fixos aqui."""

from __future__ import annotations


SEARCH = "search"
DOCS = "docs"


def normalize_api_base(raw: str) -> str:
    return raw.strip().rstrip("/")


def endpoint_url(base: str, resource: str) -> str:
    b = normalize_api_base(base)
    r = resource.strip().lstrip("/")
    return f"{b}/{r}"


def search_url(base: str) -> str:
    return endpoint_url(base, SEARCH)

def create_doc_url(base: str) -> str:
    return endpoint_url(base, DOCS)


def health_url(base: str) -> str:
    return endpoint_url(base, "health")

