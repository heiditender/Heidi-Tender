from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client import models
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.core.config import get_settings
from apps.api.models.db import Chunk, DocumentRef, TenderNotice
from apps.api.services.docs.chunking import chunk_text
from apps.api.services.docs.fetch import DocumentFetcher
from apps.api.services.docs.pdf_extract import extract_html_text, extract_pdf_text
from apps.api.services.indexing.qdrant_client import get_qdrant_client
from apps.api.services.retrieval.embeddings import get_embedding_service

logger = logging.getLogger(__name__)


class ReindexStats(dict):
    notices: int
    documents: int
    chunks: int
    vectors_upserted: int
    elapsed_ms: int


def _build_chunk_metadata(notice: TenderNotice, doc: DocumentRef | None) -> dict[str, Any]:
    return {
        "source": notice.source,
        "language": (notice.languages or [None])[0],
        "publication_date": notice.publication_date.isoformat() if notice.publication_date else None,
        "deadline_date": notice.deadline_date.isoformat() if notice.deadline_date else None,
        "buyer": notice.buyer_name,
        "region": notice.region,
        "cpv": notice.cpv_codes or [],
        "url": notice.url,
        "doc_url": doc.url if doc else None,
        "section_hint": doc.filename if doc and doc.filename else "notice_description",
    }


def _ensure_document_text(doc: DocumentRef, fetcher: DocumentFetcher) -> None:
    if doc.text:
        return

    if not doc.raw_bytes_path and doc.url:
        cache_result = fetcher.fetch_to_cache(doc.notice_id, doc.url)
        if cache_result:
            doc.raw_bytes_path = cache_result["path"]
            doc.sha256 = cache_result["sha256"]
            doc.mime_type = doc.mime_type or cache_result.get("mime_type")
            doc.fetched_at = datetime.now(timezone.utc)

    if not doc.raw_bytes_path:
        return

    mime = (doc.mime_type or "").lower()
    if doc.raw_bytes_path.lower().endswith(".pdf") or "pdf" in mime:
        text, pages = extract_pdf_text(doc.raw_bytes_path)
        doc.text = text
        doc.pages = pages
    elif doc.raw_bytes_path.lower().endswith(".html") or "html" in mime:
        doc.text = extract_html_text(doc.raw_bytes_path)


def reindex_notices(db: Session, notice_ids: list[str] | None = None, full: bool = False) -> dict[str, int]:
    started = time.perf_counter()
    settings = get_settings()
    fetcher = DocumentFetcher()
    embedder = get_embedding_service()
    qdrant = get_qdrant_client()

    stmt = select(TenderNotice)
    if notice_ids:
        stmt = stmt.where(TenderNotice.id.in_(notice_ids))

    notices = list(db.scalars(stmt).all())
    total_docs = 0
    total_chunks = 0
    vectors_upserted = 0

    for notice in notices:
        docs = list(db.scalars(select(DocumentRef).where(DocumentRef.notice_id == notice.id)).all())
        total_docs += len(docs)

        # refresh document cache/text when needed
        for doc in docs:
            _ensure_document_text(doc, fetcher)

        # wipe old chunks for this notice
        old_chunks = list(db.scalars(select(Chunk).where(Chunk.notice_id == notice.id)).all())
        old_chunk_ids = [c.chunk_id for c in old_chunks]
        if old_chunk_ids:
            db.execute(delete(Chunk).where(Chunk.notice_id == notice.id))
            try:
                qdrant.delete(
                    collection_name=settings.qdrant_collection,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="notice_id",
                                    match=models.MatchValue(value=notice.id),
                                )
                            ]
                        )
                    ),
                    wait=True,
                )
            except Exception as exc:
                logger.warning("Qdrant delete existing chunks failed notice=%s err=%s", notice.id, exc)

        chunk_rows: list[Chunk] = []
        points: list[models.PointStruct] = []

        def add_chunks(text: str, doc: DocumentRef | None) -> None:
            nonlocal total_chunks, vectors_upserted
            if not text:
                return
            base_meta = _build_chunk_metadata(notice, doc)
            chunks = chunk_text(text, base_metadata=base_meta)
            if not chunks:
                return

            vectors = embedder.embed_texts([c["text"] for c in chunks])
            for i, c in enumerate(chunks):
                row = Chunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc.doc_id if doc else None,
                    notice_id=notice.id,
                    chunk_index=c["chunk_index"],
                    text=c["text"],
                    metadata_json=c["metadata"],
                )
                chunk_rows.append(row)
                payload = {
                    "source": notice.source,
                    "notice_id": notice.id,
                    "doc_id": doc.doc_id if doc else None,
                    "buyer_name": notice.buyer_name,
                    "region": notice.region,
                    "cpv_codes": notice.cpv_codes or [],
                    "publication_date": notice.publication_date.isoformat() if notice.publication_date else None,
                    "deadline_date": notice.deadline_date.isoformat() if notice.deadline_date else None,
                    "language": (notice.languages or [None])[0],
                    "url": notice.url,
                    "doc_url": doc.url if doc else None,
                    "title": notice.title,
                    "text": c["text"],
                }
                points.append(
                    models.PointStruct(
                        id=row.chunk_id,
                        vector=vectors[i],
                        payload=payload,
                    )
                )

            total_chunks += len(chunks)

        for doc in docs:
            if doc.text:
                add_chunks(doc.text, doc)

        if full or not docs:
            if notice.description:
                add_chunks(notice.description, None)

        for row in chunk_rows:
            db.add(row)

        if points:
            try:
                qdrant.upsert(collection_name=settings.qdrant_collection, points=points, wait=True)
                vectors_upserted += len(points)
            except Exception as exc:
                logger.warning("Qdrant upsert failed notice=%s err=%s", notice.id, exc)

    db.commit()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "notices": len(notices),
        "documents": total_docs,
        "chunks": total_chunks,
        "vectors_upserted": vectors_upserted,
        "elapsed_ms": elapsed_ms,
    }
