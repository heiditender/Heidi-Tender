from __future__ import annotations

import json
from queue import Queue
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import SessionUser, get_current_user
from ..config import Settings, get_settings
from ..db import get_db
from ..models import RuleSource, RuleStatus
from ..repositories.app_settings import AppSettingsRepository
from ..repositories.auth import AuthRepository
from ..repositories.rules import RuleRepository
from ..schemas import (
    GenerateRulesRequest,
    GenerateRulesStreamRequest,
    PublishRuleResponse,
    RuleVersionResponse,
    SaveRuleDraftRequest,
)
from ..services.auth import enforce_same_origin, get_request_ip, get_request_user_agent
from ..services.rules import (
    allowed_fields_from_schema,
    ensure_openai_key,
    fetch_schema_payload,
    generate_rules_with_llm,
    sanitize_copilot_rule_payload,
    validate_rule_payload,
)


router = APIRouter(prefix="/rules", tags=["rules"])


def _to_response(row) -> RuleVersionResponse:
    return RuleVersionResponse(
        id=row.id,
        version_number=row.version_number,
        status=row.status,
        source=row.source,
        payload=row.payload,
        validation_report=row.validation_report,
        copilot_log=row.copilot_log,
        note=row.note,
        created_at=row.created_at,
        published_at=row.published_at,
    )


def _log_rules_event(
    *,
    db: Session,
    current_user: SessionUser,
    request: Request,
    event_type: str,
    version_id: str,
    payload: dict | None = None,
) -> None:
    AuthRepository(db).log_event(
        event_type=event_type,
        actor_user_id=current_user.user.id,
        target_type="rule_version",
        target_id=version_id,
        email=current_user.user.primary_email,
        ip_address=get_request_ip(request),
        user_agent=get_request_user_agent(request),
        payload=payload or {},
    )


@router.get("/current", response_model=RuleVersionResponse)
def get_current_rules(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> RuleVersionResponse:
    repo = RuleRepository(db)
    row = repo.get_current_published()
    if row is None:
        raise HTTPException(status_code=404, detail="no published rules")
    return _to_response(row)


@router.get("/versions", response_model=list[RuleVersionResponse])
def list_rule_versions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
    status: Annotated[RuleStatus | None, Query()] = None,
    source: Annotated[RuleSource | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RuleVersionResponse]:
    repo = RuleRepository(db)
    rows = repo.list_versions(status=status, source=source, query=q, limit=limit, offset=offset)
    return [_to_response(row) for row in rows]


@router.post("/draft", response_model=RuleVersionResponse)
def save_rule_draft(
    http_request: Request,
    request: SaveRuleDraftRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> RuleVersionResponse:
    enforce_same_origin(http_request, settings)
    schema_payload = fetch_schema_payload(settings)
    allowed_fields = allowed_fields_from_schema(schema_payload)

    normalized_payload, report = validate_rule_payload(request.payload.model_dump(mode="python"), allowed_fields)
    copilot_log = request.copilot_log.model_dump(mode="python") if request.copilot_log else None

    repo = RuleRepository(db)
    row = repo.create_version(
        payload=normalized_payload,
        status=RuleStatus.draft,
        source=request.source,
        validation_report=report,
        copilot_log=copilot_log,
        note=request.note,
        created_by_user_id=current_user.user.id,
    )
    return _to_response(row)


@router.post("/generate", response_model=RuleVersionResponse)
def generate_rule_draft(
    http_request: Request,
    request: GenerateRulesRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> RuleVersionResponse:
    enforce_same_origin(http_request, settings)
    schema_payload = fetch_schema_payload(settings)
    allowed_fields = allowed_fields_from_schema(schema_payload)
    settings_repo = AppSettingsRepository(db)
    model = settings_repo.get_current_openai_model(
        default_model=settings.openai_model,
        allowed_models=settings.allowed_openai_models,
    )

    generated_payload, execution_summary = generate_rules_with_llm(
        settings=settings,
        schema_payload=schema_payload,
        allowed_fields=allowed_fields,
        model=model,
        user_prompt="",
    )
    sanitized_payload, _ = sanitize_copilot_rule_payload(generated_payload)
    normalized_payload, report = validate_rule_payload(sanitized_payload, allowed_fields)

    repo = RuleRepository(db)
    row = repo.create_version(
        payload=normalized_payload,
        status=RuleStatus.draft,
        source=RuleSource.llm,
        validation_report=report,
        copilot_log={
            "prompt": "",
            "model": model,
            "reasoning_summary": execution_summary.get("reasoning_summary"),
            "execution_summary": execution_summary,
        },
        note=request.note,
        created_by_user_id=current_user.user.id,
    )
    return _to_response(row)


def _encode_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/generate/stream")
def generate_rule_preview_stream(
    http_request: Request,
    request: GenerateRulesStreamRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
):
    enforce_same_origin(http_request, settings)
    ensure_openai_key(settings)
    schema_payload = fetch_schema_payload(settings)
    allowed_fields = allowed_fields_from_schema(schema_payload)
    settings_repo = AppSettingsRepository(db)
    model = settings_repo.get_current_openai_model(
        default_model=settings.openai_model,
        allowed_models=settings.allowed_openai_models,
    )
    prompt = request.prompt.strip()

    queue: Queue[object] = Queue()
    sentinel = object()

    def _worker() -> None:
        try:
            def _on_stream_event(event: dict) -> None:
                kind = str(event.get("kind") or "status")
                if kind not in {"status", "reasoning_summary_delta", "reasoning_summary", "execution_summary"}:
                    return
                queue.put((kind, event))

            generated_payload, execution_summary = generate_rules_with_llm(
                settings=settings,
                schema_payload=schema_payload,
                allowed_fields=allowed_fields,
                model=model,
                user_prompt=prompt,
                on_stream_event=_on_stream_event,
            )
            sanitized_payload, sanitization_warnings = sanitize_copilot_rule_payload(generated_payload)
            normalized_payload, report = validate_rule_payload(sanitized_payload, allowed_fields)
            preview_event = {
                "preview_payload": normalized_payload,
                "validation_report": report,
                "llm_execution_summary": execution_summary,
                "model": model,
            }
            if sanitization_warnings:
                preview_event["sanitization_warnings"] = sanitization_warnings
            queue.put(("preview_payload", preview_event))
            queue.put(("done", {"ok": True}))
        except HTTPException as exc:
            queue.put(("error", {"message": str(exc.detail)}))
        except Exception as exc:
            queue.put(("error", {"message": str(exc)}))
        finally:
            queue.put(sentinel)

    threading.Thread(target=_worker, daemon=True).start()

    def _event_stream():
        while True:
            item = queue.get()
            if item is sentinel:
                break
            event, payload = item
            yield _encode_sse(event, payload)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/{version_id}/publish", response_model=PublishRuleResponse)
def publish_rule_version(
    version_id: str,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> PublishRuleResponse:
    enforce_same_origin(http_request, settings)
    repo = RuleRepository(db)
    try:
        row = repo.publish(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="conflict while publishing rule version") from exc
    if row.published_at is None:
        raise HTTPException(status_code=500, detail="rule publish timestamp is missing")
    _log_rules_event(
        db=db,
        current_user=current_user,
        request=http_request,
        event_type="rules.published",
        version_id=row.id,
        payload={"version_number": row.version_number},
    )
    return PublishRuleResponse(id=row.id, status=row.status, published_at=row.published_at)
