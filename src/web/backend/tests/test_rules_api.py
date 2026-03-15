from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import rules as rules_api
from app.config import Settings
from app.db import Base
from app.schemas import GenerateRulesRequest, GenerateRulesStreamRequest


def _build_session(tmp_path: Path) -> tuple[Session, Settings]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    settings = Settings(openai_api_key="test-key", jobs_root=tmp_path / "jobs")
    return testing_session(), settings


def _mock_rule_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    schema_payload = {
        "tables": [
            {
                "name": "vw_bid_specs",
                "columns": [
                    {"name": "ugr", "type": "double"},
                ],
            }
        ]
    }
    llm_payload = {
        "field_rules": [
            {
                "field": "vw_bid_specs.ugr",
                "operator": "lte",
                "is_hard": True,
                "operator_confidence": 0.95,
                "hardness_confidence": 0.9,
                "rationale": "UGR is a primary glare constraint.",
                "value": 19,
            }
        ]
    }
    llm_summary = {
        "step_name": "rules_copilot_generate",
        "request_started_at": None,
        "request_finished_at": None,
        "duration_ms": 12,
        "final_status": "succeeded",
        "response_received": True,
        "fallback_used": False,
        "failure_message": None,
        "reasoning_summary": None,
        "reasoning_chars": 0,
        "stream_event_counts": {},
        "status_events": ["llm_request_started", "llm_response_received"],
    }

    monkeypatch.setattr(rules_api, "fetch_schema_payload", lambda settings: schema_payload)
    monkeypatch.setattr(rules_api, "generate_rules_with_llm", lambda **kwargs: (llm_payload, llm_summary))


def _parse_sse_payloads(raw_text: str) -> dict[str, list[dict]]:
    parsed: dict[str, list[dict]] = {}
    current_event = "message"
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal current_event, data_lines
        if not data_lines:
            current_event = "message"
            return
        parsed.setdefault(current_event, []).append(json.loads("\n".join(data_lines)))
        current_event = "message"
        data_lines = []

    for line in raw_text.splitlines():
        if not line:
            flush()
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    flush()
    return parsed


def test_generate_rule_draft_endpoint_sanitizes_extra_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, settings = _build_session(tmp_path)
    _mock_rule_generation(monkeypatch)

    try:
        response = rules_api.generate_rule_draft(
            request=GenerateRulesRequest(note="copilot draft"),
            db=db,
            settings=settings,
        )
    finally:
        db.close()

    rule = response.payload["field_rules"][0]
    assert rule["field"] == "vw_bid_specs.ugr"
    assert "value" not in rule


@pytest.mark.anyio
async def test_generate_rule_preview_stream_returns_sanitized_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, settings = _build_session(tmp_path)
    _mock_rule_generation(monkeypatch)

    try:
        response = rules_api.generate_rule_preview_stream(
            request=GenerateRulesStreamRequest(prompt="office lighting"),
            db=db,
            settings=settings,
        )
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    finally:
        db.close()

    events = _parse_sse_payloads("".join(chunks))
    preview_event = events["preview_payload"][0]
    rule = preview_event["preview_payload"]["field_rules"][0]

    assert rule["field"] == "vw_bid_specs.ugr"
    assert "value" not in rule
    assert preview_event["sanitization_warnings"] == [
        "Removed unsupported Copilot keys from 1 row: value."
    ]
