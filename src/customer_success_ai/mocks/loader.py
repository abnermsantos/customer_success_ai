from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def load_tickets_history(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))

