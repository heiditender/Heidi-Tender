from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.models.db import DocumentRef, TenderNotice, get_db_session
from apps.api.models.schemas import ChangesResponse, ChecklistResponse, DocumentRefOut, TenderNoticeOut
from apps.api.services.analysis.changes import calculate_changes
from apps.api.services.analysis.checklist import generate_checklist

router = APIRouter(prefix="/notices", tags=["notices"])


@router.get("/{notice_id}", response_model=TenderNoticeOut)
def get_notice(notice_id: str, db: Session = Depends(get_db_session)):
    notice = db.scalar(select(TenderNotice).where(TenderNotice.id == notice_id))
    if not notice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found")

    docs = list(db.scalars(select(DocumentRef).where(DocumentRef.notice_id == notice_id)).all())
    return TenderNoticeOut(
        id=notice.id,
        source=notice.source,
        source_id=notice.source_id,
        title=notice.title,
        description=notice.description,
        buyer_name=notice.buyer_name,
        buyer_location=notice.buyer_location,
        cpv_codes=notice.cpv_codes,
        procedure_type=notice.procedure_type,
        publication_date=notice.publication_date,
        deadline_date=notice.deadline_date,
        languages=notice.languages,
        region=notice.region,
        url=notice.url,
        documents=[
            DocumentRefOut(
                doc_id=d.doc_id,
                url=d.url,
                filename=d.filename,
                mime_type=d.mime_type,
                fetched_at=d.fetched_at,
                sha256=d.sha256,
                pages=d.pages,
                raw_bytes_path=d.raw_bytes_path,
            )
            for d in docs
        ],
    )


@router.get("/{notice_id}/checklist", response_model=ChecklistResponse)
def get_checklist(notice_id: str, db: Session = Depends(get_db_session)):
    try:
        return generate_checklist(db, notice_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{notice_id}/changes", response_model=ChangesResponse)
def get_changes(notice_id: str, db: Session = Depends(get_db_session)):
    notice = db.scalar(select(TenderNotice).where(TenderNotice.id == notice_id))
    if not notice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notice not found")
    return calculate_changes(db, notice_id)
