from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI

from customer_success_ai.integrations.loader import KbDoc, fetch_kb_search, fetch_tickets_history
from customer_success_ai.observability import JsonlLogger, StepTimer
from customer_success_ai.rag.models import Citation
from customer_success_ai.workflow.state import Ticket


def _kb_to_documents(kb_docs: list[KbDoc]) -> list[Document]:
    docs: list[Document] = []
    for d in kb_docs:
        docs.append(
            Document(
                page_content=d.content,
                metadata={
                    "source": "kb",
                    "doc_id": d.doc_id,
                    "title": d.title,
                    "category": d.category,
                    "tags": d.tags,
                    "module": d.module,
                    "path": d.source_path,
                },
            )
        )
    return docs

def _tickets_to_documents(history: list[dict[str, Any]]) -> list[Document]:
    docs: list[Document] = []
    for t in history:
        content = f"{t.get('titulo','')}\n{t.get('descricao','')}".strip()
        docs.append(
            Document(
                page_content=content,
                metadata={
                    "source": "tickets",
                    "ticket_id": t.get("id"),
                    "tipo": t.get("tipo"),
                    "status": t.get("status"),
                    "prioridade": t.get("prioridade"),
                    "id_cliente": t.get("id_cliente"),
                    "nome_cliente": t.get("nome_cliente"),
                },
            )
        )
    return docs

def _split_docs(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    return splitter.split_documents(docs)

def _rerank_with_llm(query: str, candidates: list[Document], *, logger: JsonlLogger, model: str = "gpt-4o-mini") -> list[Document]:
    """Re-ranking (técnica avançada) via LLM, retornando candidatos ordenados."""
    with StepTimer(logger, "rag_rerank"):
        llm = ChatOpenAI(model=model, temperature=0)
        packed = []
        for i, d in enumerate(candidates):
            meta = d.metadata
            packed.append(
                {
                    "i": i,
                    "source": meta.get("source"),
                    "ref": meta.get("doc_id") or meta.get("ticket_id"),
                    "title": meta.get("title"),
                    "text": d.page_content[:700],
                    "meta": meta,
                }
            )

        prompt = {
            "query": query,
            "candidates": packed,
            "instructions": "Ordene os candidatos por relevância para responder o ticket. Responda apenas JSON: {order:[i...]}.",
        }
        raw = llm.invoke(
            [
                {"role": "system", "content": "Você é um re-ranker de documentos para RAG. Responda somente JSON válido."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ]
        ).content
        ranked = candidates
        try:
            data = json.loads(raw) if isinstance(raw, str) else {}
            order = data.get("order", [])
            ranked = [candidates[i] for i in order if isinstance(i, int) and 0 <= i < len(candidates)]
            if not ranked:
                ranked = candidates
                logger.log("rerank_fallback", reason="empty_or_bad_order")
        except json.JSONDecodeError as e:
            logger.log("rerank_fallback", reason="invalid_json", error=str(e), raw_preview=str(raw)[:200])
            ranked = candidates
        logger.log("rerank_done", candidates=len(candidates), returned=len(ranked))
        return ranked

def retrieve_context(
    ticket: Ticket,
    *,
    logger: JsonlLogger,
    top_k: int = 5,
) -> tuple[list[Document], list[Citation]]:
    with StepTimer(logger, "rag_retrieve"):
        kb_docs = fetch_kb_search(
            category=str(ticket.get("tipo") or "").strip().lower(),
            limit=50,
            timeout=120.0,
        )
        history = fetch_tickets_history(
            timeout=120.0,
            tipo=str(ticket.get("tipo") or "").strip().lower() or None,
            status="finalizado",
            customer_id=None,
            limit=800,
        )

        docs = _split_docs(_kb_to_documents(kb_docs) + _tickets_to_documents(history))
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        vs = FAISS.from_documents(docs, embeddings)

        query = f"{ticket['titulo']}\n{ticket['descricao']}\nTipo: {ticket['tipo']}"
        retrieved = vs.similarity_search(query, k=min(20, max(top_k, 10)))
        reranked = _rerank_with_llm(query, retrieved, logger=logger)
        final_docs = reranked[:top_k]

        citations: list[Citation] = []
        for d in final_docs:
            meta = d.metadata
            citations.append(
                Citation(
                    source=str(meta.get("source")),
                    ref=str(meta.get("doc_id") or meta.get("ticket_id") or ""),
                    path=meta.get("path"),
                    snippet=d.page_content[:240],
                    metadata={k: v for k, v in meta.items() if k not in ("path",)},
                )
            )

        logger.log(
            "rag_selected",
            selected=[asdict(c) for c in citations],
        )
        return final_docs, citations
