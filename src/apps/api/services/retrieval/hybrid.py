from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from qdrant_client import models
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.core.config import get_settings
from apps.api.models.db import Chunk, TenderNotice
from apps.api.models.schemas import ChatFilters
from apps.api.services.indexing.qdrant_client import get_qdrant_client
from apps.api.services.retrieval.embeddings import get_embedding_service

logger = logging.getLogger(__name__)


@dataclass
class RetrievalCandidate:
    chunk_id: str
    notice_id: str
    doc_id: str | None
    title: str | None
    url: str | None
    doc_url: str | None
    text: str
    dense_score: float
    bm25_score: float = 0.0
    final_score: float = 0.0
    metadata: dict[str, Any] | None = None


def _normalize(scores: list[float]) -> list[float]:
    if not scores:
        return []
    mn = min(scores)
    mx = max(scores)
    if mx == mn:
        return [1.0 for _ in scores]
    return [(s - mn) / (mx - mn) for s in scores]


def _tokenize(text: str) -> list[str]:
    return [x.lower() for x in text.split() if x.strip()]


def _build_qdrant_filter(filters: ChatFilters | None) -> models.Filter | None:
    if not filters:
        return None

    must_conditions: list[models.Condition] = []

    if filters.source:
        must_conditions.append(models.FieldCondition(key="source", match=models.MatchValue(value=filters.source)))
    if filters.cpv:
        must_conditions.append(models.FieldCondition(key="cpv_codes", match=models.MatchValue(value=filters.cpv[0])))
    if filters.buyer:
        must_conditions.append(models.FieldCondition(key="buyer_name", match=models.MatchText(text=filters.buyer)))
    if filters.canton:
        must_conditions.append(models.FieldCondition(key="region", match=models.MatchText(text=filters.canton)))
    if filters.language:
        must_conditions.append(models.FieldCondition(key="language", match=models.MatchValue(value=filters.language)))
    if filters.date_range and (filters.date_range.start or filters.date_range.end):
        gte = filters.date_range.start.isoformat() if filters.date_range.start else None
        lte = filters.date_range.end.isoformat() if filters.date_range.end else None
        must_conditions.append(models.FieldCondition(key="deadline_date", range=models.DatetimeRange(gte=gte, lte=lte)))

    if not must_conditions:
        return None
    return models.Filter(must=must_conditions)


def _db_fallback_candidates(db: Session, filters: ChatFilters | None, limit: int = 200) -> list[RetrievalCandidate]:
    stmt = select(Chunk, TenderNotice).join(TenderNotice, TenderNotice.id == Chunk.notice_id)

    if filters:
        if filters.source:
            stmt = stmt.where(TenderNotice.source == filters.source)
        if filters.buyer:
            stmt = stmt.where(TenderNotice.buyer_name.ilike(f"%{filters.buyer}%"))
        if filters.canton:
            stmt = stmt.where(TenderNotice.region.ilike(f"%{filters.canton}%"))
        if filters.date_range and filters.date_range.start:
            stmt = stmt.where(TenderNotice.deadline_date >= filters.date_range.start)
        if filters.date_range and filters.date_range.end:
            stmt = stmt.where(TenderNotice.deadline_date <= filters.date_range.end)

    rows = db.execute(stmt.limit(limit)).all()
    out: list[RetrievalCandidate] = []
    for chunk, notice in rows:
        if filters and filters.language:
            langs = [str(x).lower() for x in (notice.languages or [])]
            if filters.language.lower() not in langs:
                continue
        if filters and filters.cpv:
            cpv_codes = [str(x) for x in (notice.cpv_codes or [])]
            if not any(c in cpv_codes for c in filters.cpv):
                continue

        metadata = dict(chunk.metadata_json or {})
        metadata.setdefault("buyer_name", notice.buyer_name)
        metadata.setdefault("language", (notice.languages or [None])[0])
        metadata.setdefault("region", notice.region)
        out.append(
            RetrievalCandidate(
                chunk_id=chunk.chunk_id,
                notice_id=notice.id,
                doc_id=chunk.doc_id,
                title=notice.title,
                url=notice.url,
                doc_url=(chunk.metadata_json or {}).get("doc_url"),
                text=chunk.text,
                dense_score=0.0,
                metadata=metadata,
            )
        )
    return out


def retrieve_hybrid(
    db: Session,
    question: str,
    filters: ChatFilters | None,
    dense_candidates: int | None = None,
) -> tuple[list[RetrievalCandidate], dict[str, Any]]:
    settings = get_settings()
    embedder = get_embedding_service()
    client = get_qdrant_client()

    limit = dense_candidates or settings.dense_candidates
    query_filter = _build_qdrant_filter(filters)
    results: list[RetrievalCandidate] = []
    used_dense = False

    try:
        query_vec = embedder.embed_query(question)
        points = client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vec,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        used_dense = True
        for p in points:
            payload = p.payload or {}
            text = str(payload.get("text") or "")
            results.append(
                RetrievalCandidate(
                    chunk_id=str(p.id),
                    notice_id=str(payload.get("notice_id")),
                    doc_id=(str(payload.get("doc_id")) if payload.get("doc_id") else None),
                    title=payload.get("title"),
                    url=payload.get("url"),
                    doc_url=payload.get("doc_url"),
                    text=text,
                    dense_score=float(p.score or 0.0),
                    metadata=payload,
                )
            )
    except Exception as exc:
        logger.warning("Dense retrieval failed. Falling back to DB BM25 only. err=%s", exc)

    if not results:
        results = _db_fallback_candidates(db, filters=filters, limit=300)

    corpus_tokens = [_tokenize(c.text) for c in results]
    bm25 = BM25Okapi(corpus_tokens) if corpus_tokens else None
    query_tokens = _tokenize(question)
    if bm25 and query_tokens:
        bm25_scores = bm25.get_scores(query_tokens).tolist()
    else:
        bm25_scores = [0.0 for _ in results]

    dense_norm = _normalize([c.dense_score for c in results])
    bm25_norm = _normalize(bm25_scores)

    for i, c in enumerate(results):
        c.bm25_score = bm25_scores[i]
        c.final_score = settings.dense_weight * dense_norm[i] + settings.bm25_weight * bm25_norm[i]

    results.sort(key=lambda x: x.final_score, reverse=True)

    stats = {
        "used_dense": used_dense,
        "candidate_count": len(results),
        "dense_candidates": limit,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return results, stats
