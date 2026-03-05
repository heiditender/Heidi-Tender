from __future__ import annotations

import re
from collections import defaultdict

from apps.api.models.schemas import ChatFilters
from apps.api.services.retrieval.hybrid import RetrievalCandidate


KEY_TERMS = {
    "deadline": ["deadline", "due date", "submission", "closing"],
    "requirements": ["requirement", "must", "mandatory", "eligibility", "qualification"],
    "documents": ["document", "annex", "certificate", "statement", "submit"],
    "evaluation": ["evaluation", "criteria", "weight", "award"],
}


def _contains_any(text: str, terms: list[str]) -> bool:
    txt = text.lower()
    return any(term in txt for term in terms)


def rerank_candidates(
    question: str,
    candidates: list[RetrievalCandidate],
    filters: ChatFilters | None,
    top_k: int,
) -> list[RetrievalCandidate]:
    q = question.lower()

    for c in candidates:
        boost = 0.0
        text = c.text.lower()

        for term_group in KEY_TERMS.values():
            if _contains_any(q, term_group) and _contains_any(text, term_group):
                boost += 0.08

        if filters:
            if filters.buyer and c.metadata and c.metadata.get("buyer_name"):
                if filters.buyer.lower() in str(c.metadata.get("buyer_name", "")).lower():
                    boost += 0.05
            if filters.language and c.metadata and c.metadata.get("language"):
                if filters.language.lower() == str(c.metadata.get("language")).lower():
                    boost += 0.04
            if filters.canton and c.metadata and c.metadata.get("region"):
                if filters.canton.lower() in str(c.metadata.get("region")).lower():
                    boost += 0.04

        # Slight penalty for very short chunks.
        text_len = len(re.findall(r"\w+", c.text))
        if text_len < 40:
            boost -= 0.03

        c.final_score += boost

    candidates.sort(key=lambda x: x.final_score, reverse=True)

    # Keep best chunk per notice first, then fill remaining slots with next best chunks.
    by_notice: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for c in candidates:
        by_notice[c.notice_id].append(c)

    selected: list[RetrievalCandidate] = []
    for notice_id in by_notice:
        selected.append(by_notice[notice_id][0])
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        for c in candidates:
            if c not in selected:
                selected.append(c)
            if len(selected) >= top_k:
                break

    return selected
