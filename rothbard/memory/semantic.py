"""Semantic memory — ChromaDB vector store.

Stores embeddings of opportunities, decisions, and learnings. Lets the
agent recall past experiences when evaluating new opportunities of the
same type (e.g. "last time I tried this DeFi pool, gas killed the profit").
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_client = None
_collection = None


async def init_semantic(host: str, port: int) -> None:
    global _client, _collection
    try:
        import chromadb  # type: ignore[import]

        _client = chromadb.HttpClient(host=host, port=port)
        _collection = _client.get_or_create_collection(
            name="rothbard_memory",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Semantic memory connected to %s:%s", host, port)
    except Exception as exc:
        logger.warning("ChromaDB unavailable, semantic memory disabled: %s", exc)


async def store(
    doc_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if _collection is None:
        return
    try:
        _collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
    except Exception as exc:
        logger.error("Semantic store failed: %s", exc)


async def recall(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """Return top-n semantically similar memories."""
    if _collection is None:
        return []
    try:
        results = _collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        items = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            items.append({"text": doc, "metadata": meta, "distance": dist})
        return items
    except Exception as exc:
        logger.error("Semantic recall failed: %s", exc)
        return []


async def store_opportunity_outcome(
    opportunity_type: str,
    description: str,
    outcome: str,
    profit_usdc: str,
    cycle: int,
) -> None:
    """Convenience helper: embed what happened with a given opportunity."""
    doc_id = f"opp:{opportunity_type}:{cycle}"
    text = (
        f"Opportunity type: {opportunity_type}\n"
        f"Description: {description}\n"
        f"Outcome: {outcome}\n"
        f"Profit: {profit_usdc} USDC"
    )
    await store(
        doc_id=doc_id,
        text=text,
        metadata={
            "type": opportunity_type,
            "outcome": outcome,
            "profit_usdc": profit_usdc,
            "cycle": cycle,
        },
    )
