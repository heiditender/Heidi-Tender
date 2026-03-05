from __future__ import annotations

import re
from collections import Counter

STOPWORDS = {
    "the",
    "is",
    "are",
    "a",
    "an",
    "what",
    "which",
    "for",
    "in",
    "of",
    "to",
    "and",
    "on",
    "with",
    "next",
    "days",
    "please",
}


def _extract_keywords(question: str, top_n: int = 8) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_-]+", question.lower())
    tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    if not tokens:
        return []
    return [k for k, _ in Counter(tokens).most_common(top_n)]


def build_plan(question: str, filters: dict | None = None) -> dict:
    keywords = _extract_keywords(question)

    retrieval_queries = [question]
    if keywords:
        retrieval_queries.append(" ".join(keywords[:5]))

    return {
        "sub_questions": [
            "Identify tenders matching user intent and filters.",
            "Extract deadlines and mandatory requirements from top evidence.",
        ],
        "keywords": keywords,
        "filter_suggestions": filters or {},
        "retrieval_queries": retrieval_queries,
        "max_rounds": 2,
    }
