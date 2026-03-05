from __future__ import annotations

import logging
from functools import lru_cache

from qdrant_client import QdrantClient, models

from apps.api.core.config import get_settings
from apps.api.services.retrieval.embeddings import get_embedding_service

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, timeout=settings.qdrant_timeout)


def ensure_collection() -> None:
    settings = get_settings()
    embedder = get_embedding_service()
    client = get_qdrant_client()
    collection = settings.qdrant_collection

    exists = client.collection_exists(collection_name=collection)
    if not exists:
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=embedder.dimension, distance=models.Distance.COSINE),
        )
        logger.info("Created Qdrant collection name=%s dim=%s", collection, embedder.dimension)
    else:
        info = client.get_collection(collection_name=collection)
        vectors_cfg = info.config.params.vectors
        size = getattr(vectors_cfg, "size", None)
        if size is None and isinstance(vectors_cfg, dict):
            # Named vectors case: pick first vector size for compatibility.
            first = next(iter(vectors_cfg.values()))
            size = getattr(first, "size", None)
        if size != embedder.dimension:
            if settings.qdrant_recreate_collection:
                client.delete_collection(collection_name=collection)
                client.create_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(size=embedder.dimension, distance=models.Distance.COSINE),
                )
                logger.warning(
                    "Recreated Qdrant collection due to vector size mismatch old=%s new=%s", size, embedder.dimension
                )
            else:
                logger.warning(
                    "Qdrant vector dim mismatch collection=%s current=%s expected=%s",
                    collection,
                    size,
                    embedder.dimension,
                )

    # Create payload indexes (idempotent)
    indexed_fields = {
        "notice_id": models.PayloadSchemaType.KEYWORD,
        "cpv_codes": models.PayloadSchemaType.KEYWORD,
        "deadline_date": models.PayloadSchemaType.DATETIME,
        "publication_date": models.PayloadSchemaType.DATETIME,
        "source": models.PayloadSchemaType.KEYWORD,
        "buyer_name": models.PayloadSchemaType.KEYWORD,
        "region": models.PayloadSchemaType.KEYWORD,
        "language": models.PayloadSchemaType.KEYWORD,
    }

    for field, schema in indexed_fields.items():
        try:
            client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=schema,
                wait=True,
            )
        except Exception as exc:
            # Index may already exist.
            logger.debug("Skipping payload index field=%s err=%s", field, exc)
