from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np

from customer_success_ai.storage.base import PersistedRun
from customer_success_ai.workflow.state import WorkflowState


def _to_jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return str(obj)


class SQLiteRunStorage:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  run_id TEXT PRIMARY KEY,
                  created_at_utc TEXT NOT NULL,
                  as_of_utc TEXT,
                  ticket_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  customer_name TEXT,
                  ticket_title TEXT,
                  ticket_text TEXT,
                  ticket_raw_json TEXT NOT NULL,
                  classification_error TEXT,
                  specialist TEXT,
                  draft_final TEXT,
                  confidence REAL,
                  requires_human_review INTEGER NOT NULL DEFAULT 0,
                  is_sensitive INTEGER NOT NULL DEFAULT 0,
                  open_tickets_for_customer INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS triage (
                  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
                  category TEXT,
                  urgency TEXT,
                  confidence REAL,
                  rationale TEXT,
                  triage_raw_json TEXT
                );

                CREATE TABLE IF NOT EXISTS rag_citations (
                  run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                  idx INTEGER NOT NULL,
                  source TEXT,
                  ref TEXT,
                  path TEXT,
                  snippet TEXT,
                  metadata_json TEXT,
                  PRIMARY KEY(run_id, idx)
                );

                CREATE TABLE IF NOT EXISTS hil (
                  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
                  decision TEXT,
                  correction TEXT
                );

                CREATE TABLE IF NOT EXISTS kb (
                  run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
                  generate_requested INTEGER,
                  article_markdown TEXT,
                  validation_decision TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_runs_ticket_id ON runs(ticket_id);
                CREATE INDEX IF NOT EXISTS idx_runs_customer_id ON runs(customer_id);

                CREATE TABLE IF NOT EXISTS feedback_memory (
                  feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at_utc TEXT NOT NULL,
                  run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                  ticket_id TEXT,
                  customer_id TEXT,
                  category TEXT,
                  hil_decision TEXT NOT NULL,
                  ticket_text TEXT NOT NULL,
                  draft_before TEXT,
                  human_correction TEXT,
                  rejection_reason TEXT,
                  triage_raw_json TEXT,
                  embedding_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback_memory(category);
                """
            )
            # Migração simples: adiciona coluna `as_of_utc` em bases existentes.
            try:
                conn.execute("ALTER TABLE runs ADD COLUMN as_of_utc TEXT")
            except sqlite3.OperationalError:
                # Coluna já existe (ou tabela não existe em casos raros).
                pass

    def save_run(self, *, run_id: str, created_at_utc: str, state: WorkflowState) -> None:
        t = state.ticket
        ticket_text = f"{t.get('titulo','')}\n{t.get('descricao','')}".strip()

        triage = state.triage
        triage_raw = json.dumps(_to_jsonable(triage), ensure_ascii=False) if triage is not None else None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs(
                  run_id, created_at_utc, as_of_utc,
                  ticket_id, customer_id, customer_name, ticket_title, ticket_text,
                  ticket_raw_json, classification_error,
                  specialist, draft_final, confidence,
                  requires_human_review, is_sensitive, open_tickets_for_customer
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    created_at_utc,
                    state.as_of_utc,
                    t["id"],
                    t["id_cliente"],
                    t.get("nome_cliente"),
                    t.get("titulo"),
                    ticket_text,
                    json.dumps(_to_jsonable(t), ensure_ascii=False),
                    state.classification_error,
                    state.specialist,
                    state.draft,
                    float(state.confidence or 0.0),
                    1 if state.requires_human_review else 0,
                    1 if state.is_sensitive else 0,
                    int(state.open_tickets_for_customer or 0),
                ),
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO triage(
                  run_id, category, urgency, confidence, rationale, triage_raw_json
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    run_id,
                    getattr(triage, "category", None),
                    getattr(triage, "urgency", None),
                    float(getattr(triage, "confidence", 0.0) or 0.0) if triage is not None else None,
                    getattr(triage, "rationale", None),
                    triage_raw,
                ),
            )

            conn.execute("DELETE FROM rag_citations WHERE run_id = ?", (run_id,))
            for i, c in enumerate(state.citations or []):
                conn.execute(
                    """
                    INSERT INTO rag_citations(
                      run_id, idx, source, ref, path, snippet, metadata_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        i,
                        c.get("source"),
                        c.get("ref"),
                        c.get("path"),
                        c.get("snippet"),
                        json.dumps(_to_jsonable(c.get("metadata")), ensure_ascii=False),
                    ),
                )

            conn.execute(
                """
                INSERT OR REPLACE INTO hil(run_id, decision, correction)
                VALUES(?,?,?)
                """,
                (
                    run_id,
                    state.hil_decision,
                    state.hil_correction,
                ),
            )

            kb_requested: int | None
            if state.kb_generate_requested is None:
                kb_requested = None
            else:
                kb_requested = 1 if state.kb_generate_requested else 0

            conn.execute(
                """
                INSERT OR REPLACE INTO kb(run_id, generate_requested, article_markdown, validation_decision)
                VALUES(?,?,?,?)
                """,
                (
                    run_id,
                    kb_requested,
                    state.kb_article_markdown,
                    state.kb_validation_decision,
                ),
            )

    def get_run(self, run_id: str) -> PersistedRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, created_at_utc, as_of_utc, ticket_raw_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            state: dict[str, Any] = {"ticket": json.loads(row["ticket_raw_json"])}
            state["as_of_utc"] = row["as_of_utc"]

            t_row = conn.execute("SELECT * FROM triage WHERE run_id = ?", (run_id,)).fetchone()
            if t_row:
                state["triage"] = json.loads(t_row["triage_raw_json"]) if t_row["triage_raw_json"] else None

            c_rows = conn.execute(
                "SELECT idx, source, ref, path, snippet, metadata_json FROM rag_citations WHERE run_id = ? ORDER BY idx ASC",
                (run_id,),
            ).fetchall()
            state["citations"] = [
                {
                    "source": r["source"],
                    "ref": r["ref"],
                    "path": r["path"],
                    "snippet": r["snippet"],
                    "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else None,
                }
                for r in c_rows
            ]

            runs_row = conn.execute(
                """
                SELECT
                  classification_error, specialist, draft_final, confidence,
                  requires_human_review, is_sensitive, open_tickets_for_customer
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if runs_row:
                state["classification_error"] = runs_row["classification_error"]
                state["specialist"] = runs_row["specialist"]
                state["draft"] = runs_row["draft_final"]
                state["confidence"] = runs_row["confidence"]
                state["requires_human_review"] = bool(runs_row["requires_human_review"])
                state["is_sensitive"] = bool(runs_row["is_sensitive"])
                state["open_tickets_for_customer"] = runs_row["open_tickets_for_customer"]

            hil_row = conn.execute("SELECT decision, correction FROM hil WHERE run_id = ?", (run_id,)).fetchone()
            if hil_row:
                state["hil_decision"] = hil_row["decision"]
                state["hil_correction"] = hil_row["correction"]

            kb_row = conn.execute(
                "SELECT generate_requested, article_markdown, validation_decision FROM kb WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if kb_row:
                gr = kb_row["generate_requested"]
                state["kb_generate_requested"] = None if gr is None else bool(gr)
                state["kb_article_markdown"] = kb_row["article_markdown"]
                state["kb_validation_decision"] = kb_row["validation_decision"]

            return PersistedRun(run_id=row["run_id"], created_at_utc=row["created_at_utc"], state=state)

    def save_feedback(
        self,
        *,
        created_at_utc: str,
        run_id: str | None,
        ticket_id: str | None,
        customer_id: str | None,
        category: str | None,
        hil_decision: str,
        ticket_text: str,
        draft_before: str | None,
        human_correction: str | None,
        rejection_reason: str | None,
        triage_raw: dict[str, Any] | None,
        embedding: list[float],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_memory(
                  created_at_utc, run_id, ticket_id, customer_id, category, hil_decision,
                  ticket_text, draft_before, human_correction, rejection_reason, triage_raw_json, embedding_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    created_at_utc,
                    run_id,
                    ticket_id,
                    customer_id,
                    category,
                    hil_decision,
                    ticket_text,
                    draft_before,
                    human_correction,
                    rejection_reason,
                    json.dumps(_to_jsonable(triage_raw), ensure_ascii=False) if triage_raw is not None else None,
                    json.dumps(embedding),
                ),
            )

    def search_feedback(
        self,
        *,
        query_embedding: list[float],
        category: str | None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        q = np.array(query_embedding, dtype=np.float32)
        qn = float(np.linalg.norm(q)) or 1.0
        q = q / qn

        where = ""
        args: tuple[Any, ...] = ()
        if category:
            where = "WHERE category = ?"
            args = (category,)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  feedback_id, created_at_utc, run_id, ticket_id, customer_id, category, hil_decision,
                  ticket_text, draft_before, human_correction, rejection_reason, triage_raw_json, embedding_json
                FROM feedback_memory
                {where}
                ORDER BY feedback_id DESC
                LIMIT 500
                """,
                args,
            ).fetchall()

        scored: list[dict[str, Any]] = []
        for r in rows:
            emb = json.loads(r["embedding_json"] or "[]")
            v = np.array(emb, dtype=np.float32)
            vn = float(np.linalg.norm(v)) or 1.0
            v = v / vn
            score = float(np.dot(q, v))
            scored.append(
                {
                    "feedback_id": r["feedback_id"],
                    "created_at_utc": r["created_at_utc"],
                    "run_id": r["run_id"],
                    "ticket_id": r["ticket_id"],
                    "customer_id": r["customer_id"],
                    "category": r["category"],
                    "hil_decision": r["hil_decision"],
                    "ticket_text": r["ticket_text"],
                    "draft_before": r["draft_before"],
                    "human_correction": r["human_correction"],
                    "rejection_reason": r["rejection_reason"],
                    "triage_raw": json.loads(r["triage_raw_json"]) if r["triage_raw_json"] else None,
                    "score": score,
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[: max(0, int(limit))]

