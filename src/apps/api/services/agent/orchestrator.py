from __future__ import annotations

import logging
import time
from typing import Any

from apps.api.core.config import get_settings
from apps.api.models.schemas import ChatRequest, ChatResponse, Citation, ChatDebug
from apps.api.services.agent.planner import build_plan
from apps.api.services.retrieval.hybrid import RetrievalCandidate, retrieve_hybrid
from apps.api.services.retrieval.rerank import rerank_candidates

logger = logging.getLogger(__name__)


def _build_citations(candidates: list[RetrievalCandidate]) -> list[Citation]:
    citations: list[Citation] = []
    for c in candidates:
        snippet = c.text[:300] + ("..." if len(c.text) > 300 else "")
        citations.append(
            Citation(
                title=c.title,
                url=c.url,
                doc_url=c.doc_url,
                snippet=snippet,
                score=round(c.final_score, 4),
                notice_id=c.notice_id,
            )
        )
    return citations


def _extractive_summary(question: str, candidates: list[RetrievalCandidate]) -> str:
    if not candidates:
        return "No relevant tender evidence was found for your query and filters."

    lead = [
        "Based on retrieved tender evidence, here are the key points:",
    ]

    for i, c in enumerate(candidates[:5], start=1):
        line = c.text.replace("\n", " ").strip()
        if len(line) > 220:
            line = line[:220] + "..."
        lead.append(f"{i}. {line}")

    lead.append("Use the citations to validate details in the original notice/documents.")
    return "\n".join(lead)


def _llm_answer(question: str, candidates: list[RetrievalCandidate]) -> str | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        context_blocks = []
        for i, c in enumerate(candidates[:8], start=1):
            context_blocks.append(
                f"[C{i}] title={c.title or '-'} url={c.url or '-'} doc_url={c.doc_url or '-'}\n{c.text[:1200]}"
            )

        prompt = (
            "You are Suisse Bid Match, a bidder-side tender matching copilot. Answer using only the provided evidence. "
            "If data is insufficient, say what is missing. Keep the answer concise and actionable.\n\n"
            f"Question:\n{question}\n\nEvidence:\n" + "\n\n".join(context_blocks)
        )

        resp = client.chat.completions.create(
            model=settings.openai_chat_model,
            messages=[
                {"role": "system", "content": "Return grounded answers from evidence only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM answer generation failed; fallback to extractive summary. err=%s", exc)
        return None


def run_chat(db, request: ChatRequest) -> ChatResponse:
    settings = get_settings()
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    plan = build_plan(request.question, request.filters.model_dump() if request.filters else None)
    timings["plan_ms"] = (time.perf_counter() - t0) * 1000

    queries = plan.get("retrieval_queries", [request.question])[:2]
    retrieved_map: dict[str, RetrievalCandidate] = {}
    retrieval_stats = []

    t1 = time.perf_counter()
    for q in queries:
        round_candidates, stats = retrieve_hybrid(db, q, filters=request.filters)
        retrieval_stats.append(stats)
        for c in round_candidates:
            prev = retrieved_map.get(c.chunk_id)
            if prev is None or c.final_score > prev.final_score:
                retrieved_map[c.chunk_id] = c
    timings["retrieve_ms"] = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    top_k = request.top_k or settings.default_top_k
    reranked = rerank_candidates(
        question=request.question,
        candidates=list(retrieved_map.values()),
        filters=request.filters,
        top_k=max(top_k, 8),
    )
    final_context = reranked[: max(top_k, 8)]
    timings["rerank_ms"] = (time.perf_counter() - t2) * 1000

    t3 = time.perf_counter()
    answer = _llm_answer(request.question, final_context)
    if not answer:
        answer = _extractive_summary(request.question, final_context)
    timings["answer_ms"] = (time.perf_counter() - t3) * 1000

    citations = _build_citations(final_context)
    insufficient = len(citations) < 3

    debug_obj = None
    if request.debug or settings.enable_debug_chat:
        debug_obj = ChatDebug(
            plan=plan,
            queries=queries,
            timings={k: round(v, 2) for k, v in timings.items()},
            retrieval_stats={"rounds": retrieval_stats, "merged_candidates": len(retrieved_map)},
        )

    logger.info(
        "chat_complete question_len=%s citations=%s merged_candidates=%s timings_ms=%s",
        len(request.question),
        len(citations),
        len(retrieved_map),
        {k: round(v, 2) for k, v in timings.items()},
    )

    return ChatResponse(
        answer=answer,
        citations=citations,
        used_filters=request.filters.model_dump(exclude_none=True) if request.filters else {},
        citation_count_insufficient=insufficient,
        debug=debug_obj,
    )
