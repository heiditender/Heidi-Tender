from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..auth.dependencies import SessionUser, get_current_user
from ..config import Settings, get_settings
from ..db import SessionLocal, get_db
from ..models import JobStatus
from ..repositories.auth import AuthRepository
from ..repositories.jobs import JobRepository
from ..schemas import JobCreateResponse, JobResponse, StartJobRequest
from ..services.auth import enforce_same_origin, get_request_ip, get_request_user_agent
from ..services.executor import get_job_executor
from ..services.uploads import store_archive_upload, store_single_upload


router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_to_response(
    repo: JobRepository,
    job_id: str,
    *,
    owner_user_id: str,
    warnings: list[str] | None = None,
) -> JobResponse:
    job = repo.get_job(job_id, owner_user_id=owner_user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    files = repo.list_job_files(job_id, owner_user_id=owner_user_id)
    steps = repo.list_job_steps(job_id, owner_user_id=owner_user_id)
    return JobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        runtime_dir=job.runtime_dir,
        final_output_path=job.final_output_path,
        error_message=job.error_message,
        rule_version_id=job.rule_version_id,
        warnings=warnings or [],
        file_count=len(files),
        step_count=len(steps),
        files=[
            {
                "id": row.id,
                "relative_path": row.relative_path,
                "size_bytes": row.size_bytes,
                "extension": row.extension,
                "created_at": row.created_at,
            }
            for row in files
        ],
        steps=[
            {
                "step_name": row.step_name,
                "step_status": row.step_status,
                "payload": row.payload,
                "updated_at": row.updated_at,
            }
            for row in steps
        ],
    )


def _log_job_event(
    *,
    db: Session,
    current_user: SessionUser,
    request: Request,
    event_type: str,
    job_id: str,
    payload: dict | None = None,
) -> None:
    AuthRepository(db).log_event(
        event_type=event_type,
        actor_user_id=current_user.user.id,
        target_type="job",
        target_id=job_id,
        email=current_user.user.primary_email,
        ip_address=get_request_ip(request),
        user_agent=get_request_user_agent(request),
        payload=payload or {},
    )


@router.post("", response_model=JobCreateResponse)
def create_job(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> JobCreateResponse:
    enforce_same_origin(request, settings)
    repo = JobRepository(db)
    job = repo.create_job(owner_user_id=current_user.user.id)
    repo.append_event(job_id=job.id, event_type="job_created", payload={"status": job.status.value})
    _log_job_event(db=db, current_user=current_user, request=request, event_type="job.created", job_id=job.id)
    return JobCreateResponse(id=job.id, status=job.status, created_at=job.created_at)


@router.get("", response_model=list[JobResponse])
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
    status: Annotated[JobStatus | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    updated_from: Annotated[datetime | None, Query()] = None,
    updated_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[JobResponse]:
    if updated_from and updated_to and updated_from > updated_to:
        raise HTTPException(status_code=400, detail="updated_from must be earlier than updated_to")

    repo = JobRepository(db)
    jobs = repo.list_jobs(
        owner_user_id=current_user.user.id,
        status=status,
        query=q,
        updated_from=updated_from,
        updated_to=updated_to,
        limit=limit,
        offset=offset,
    )
    if not jobs:
        return []

    job_ids = [job.id for job in jobs]
    file_counts = repo.count_job_files_bulk(job_ids)
    step_counts = repo.count_job_steps_bulk(job_ids)

    return [
        JobResponse(
            id=job.id,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            runtime_dir=job.runtime_dir,
            final_output_path=job.final_output_path,
            error_message=job.error_message,
            rule_version_id=job.rule_version_id,
            file_count=file_counts.get(job.id, 0),
            step_count=step_counts.get(job.id, 0),
            files=[],
            steps=[],
        )
        for job in jobs
    ]


@router.post("/{job_id}/file", response_model=JobResponse)
def upload_single_file(
    job_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
    file: UploadFile = File(...),
    relative_path: str = Form(...),
) -> JobResponse:
    enforce_same_origin(request, settings)
    repo = JobRepository(db)
    job = repo.get_job(job_id, owner_user_id=current_user.user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {JobStatus.running, JobStatus.succeeded}:
        raise HTTPException(status_code=409, detail=f"cannot upload files when job is {job.status.value}")

    job_dir = settings.jobs_root / job_id
    input_root = job_dir / "input"

    repo.set_job_status(job, JobStatus.uploading)
    stored = store_single_upload(
        upload=file,
        relative_path=relative_path,
        input_root=input_root,
        max_bytes=settings.upload_file_limit_bytes,
    )
    repo.add_job_file(
        job_id=job_id,
        relative_path=stored.relative_path,
        stored_path=str(stored.stored_path),
        size_bytes=stored.size_bytes,
        extension=stored.extension,
    )
    repo.set_job_status(job, JobStatus.ready)
    repo.append_event(
        job_id=job_id,
        event_type="file_uploaded",
        payload={"relative_path": stored.relative_path, "size_bytes": stored.size_bytes},
    )
    return _job_to_response(repo, job_id, owner_user_id=current_user.user.id)


@router.post("/{job_id}/archive", response_model=JobResponse)
def upload_archive(
    job_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> JobResponse:
    enforce_same_origin(request, settings)
    repo = JobRepository(db)
    job = repo.get_job(job_id, owner_user_id=current_user.user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {JobStatus.running, JobStatus.succeeded}:
        raise HTTPException(status_code=409, detail=f"cannot upload archive when job is {job.status.value}")

    job_dir = settings.jobs_root / job_id
    input_root = job_dir / "input"
    archive_root = job_dir / "_archives"

    repo.set_job_status(job, JobStatus.uploading)
    result = store_archive_upload(
        upload=file,
        input_root=input_root,
        archive_root=archive_root,
        max_archive_bytes=settings.upload_zip_limit_bytes,
        max_uncompressed_bytes=settings.upload_uncompressed_limit_bytes,
        max_files=settings.upload_max_files,
        per_file_limit_bytes=settings.upload_file_limit_bytes,
    )

    for item in result.files:
        repo.add_job_file(
            job_id=job_id,
            relative_path=item.relative_path,
            stored_path=str(item.stored_path),
            size_bytes=item.size_bytes,
            extension=item.extension,
        )

    repo.set_job_status(job, JobStatus.ready)
    repo.append_event(
        job_id=job_id,
        event_type="archive_uploaded",
        payload={
            "file_count": len(result.files),
            "total_bytes": sum(item.size_bytes for item in result.files),
            "warnings": result.warnings,
        },
    )
    return _job_to_response(repo, job_id, owner_user_id=current_user.user.id, warnings=result.warnings)


@router.post("/{job_id}/start", response_model=JobResponse)
def start_job(
    job_id: str,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
    body: StartJobRequest = Body(default_factory=StartJobRequest),
) -> JobResponse:
    enforce_same_origin(http_request, settings)
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=422,
            detail="OpenAI API key is not configured. Please configure OPENAI_API_KEY before starting jobs.",
        )
    repo = JobRepository(db)
    job = repo.get_job(job_id, owner_user_id=current_user.user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in {JobStatus.ready}:
        raise HTTPException(status_code=409, detail=f"job status must be ready, got {job.status.value}")
    if not repo.list_job_files(job_id, owner_user_id=current_user.user.id):
        raise HTTPException(status_code=400, detail="job has no uploaded files")

    repo.append_event(job_id=job_id, event_type="job_queued", payload={"rule_version_id": body.rule_version_id})
    _log_job_event(
        db=db,
        current_user=current_user,
        request=http_request,
        event_type="job.started",
        job_id=job_id,
        payload={"rule_version_id": body.rule_version_id},
    )
    executor = get_job_executor()
    executor.start_job(job_id, body.rule_version_id)
    return _job_to_response(repo, job_id, owner_user_id=current_user.user.id)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
) -> JobResponse:
    repo = JobRepository(db)
    return _job_to_response(repo, job_id, owner_user_id=current_user.user.id)


@router.get("/{job_id}/result")
def get_job_result(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[SessionUser, Depends(get_current_user)],
):
    repo = JobRepository(db)
    job = repo.get_job(job_id, owner_user_id=current_user.user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.final_output_path:
        raise HTTPException(status_code=404, detail="final output is not available yet")

    final_output_path = Path(job.final_output_path)
    if not final_output_path.exists():
        raise HTTPException(status_code=404, detail="final output file is missing")

    payload = json.loads(final_output_path.read_text(encoding="utf-8"))
    return {
        "job_id": job.id,
        "status": job.status,
        "final_output": payload,
        "steps": [
            {
                "step_name": step.step_name,
                "step_status": step.step_status,
                "payload": step.payload,
                "updated_at": step.updated_at,
            }
            for step in repo.list_job_steps(job_id, owner_user_id=current_user.user.id)
        ],
    }


@router.get("/{job_id}/events")
async def stream_job_events(
    job_id: str,
    request: Request,
    current_user: Annotated[SessionUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    with SessionLocal() as db:
        repo = JobRepository(db)
        if repo.get_job(job_id, owner_user_id=current_user.user.id) is None:
            raise HTTPException(status_code=404, detail="job not found")

    start_id = 0
    if last_event_id:
        try:
            start_id = int(last_event_id)
        except ValueError:
            start_id = 0

    async def _event_generator():
        cursor = start_id
        heartbeat = settings.sse_heartbeat_seconds
        waited = 0
        while True:
            if await request.is_disconnected():
                break

            with SessionLocal() as db:
                repo = JobRepository(db)
                events = repo.events_after(job_id=job_id, last_event_id=cursor, limit=200)

            if events:
                for event in events:
                    cursor = event.id
                    payload = json.dumps(event.payload, ensure_ascii=False)
                    yield f"id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n"
                waited = 0
                continue

            await asyncio.sleep(1)
            waited += 1
            if waited >= heartbeat:
                yield ": ping\n\n"
                waited = 0

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
