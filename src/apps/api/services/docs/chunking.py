from __future__ import annotations

import re
from typing import Any

from apps.api.services.utils import compact_whitespace


def estimate_tokens(text: str) -> int:
    # Hackathon-level approximation good enough for chunk size control.
    words = len(text.split())
    return int(words * 1.3)


def split_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    text = text.replace("\r\n", "\n")
    blocks = re.split(r"\n{2,}", text)
    cleaned = [compact_whitespace(b) for b in blocks]
    return [b for b in cleaned if b]


def chunk_text(
    text: str,
    base_metadata: dict[str, Any],
    min_tokens: int = 400,
    max_tokens: int = 900,
) -> list[dict[str, Any]]:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        if para_tokens > max_tokens:
            # Hard split oversized paragraphs by sentence-like boundaries.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                sent_tokens = estimate_tokens(sent)
                if current_parts and current_tokens + sent_tokens > max_tokens:
                    chunk_text_raw = "\n\n".join(current_parts)
                    chunks.append({"text": chunk_text_raw, "metadata": dict(base_metadata)})
                    current_parts = []
                    current_tokens = 0
                current_parts.append(sent)
                current_tokens += sent_tokens
            continue

        if current_parts and current_tokens + para_tokens > max_tokens:
            chunk_text_raw = "\n\n".join(current_parts)
            chunks.append({"text": chunk_text_raw, "metadata": dict(base_metadata)})
            current_parts = []
            current_tokens = 0

        current_parts.append(para)
        current_tokens += para_tokens

        if current_tokens >= min_tokens:
            chunk_text_raw = "\n\n".join(current_parts)
            chunks.append({"text": chunk_text_raw, "metadata": dict(base_metadata)})
            current_parts = []
            current_tokens = 0

    if current_parts:
        chunk_text_raw = "\n\n".join(current_parts)
        chunks.append({"text": chunk_text_raw, "metadata": dict(base_metadata)})

    for idx, chunk in enumerate(chunks):
        chunk["chunk_index"] = idx

    return chunks
