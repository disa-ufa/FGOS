from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from uuid import UUID

from api.db.session import SessionLocal
from api.db import models
from api.schemas.common import ArtifactsListResponse, ArtifactItem
from api.security.service_auth import require_service_auth

router = APIRouter(prefix="/v1", tags=["artifacts"], dependencies=[Depends(require_service_auth)])


def _get_db() -> Session:
    return SessionLocal()


@router.get("/documents/{doc_id}/artifacts", response_model=ArtifactsListResponse)
def list_artifacts(doc_id: UUID, chat_id: int):
    db = _get_db()
    try:
        doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
        if not doc or int(doc.telegram_chat_id) != int(chat_id):
            raise HTTPException(status_code=404, detail="Not Found")

        items = (
            db.query(models.Artifact)
            .filter(models.Artifact.doc_id == doc_id)
            .order_by(models.Artifact.created_at.desc())
            .all()
        )
        return ArtifactsListResponse(
            doc_id=doc_id,
            items=[
                ArtifactItem(
                    artifact_id=a.id,
                    doc_id=a.doc_id,
                    kind=a.kind.value,
                    filename=a.filename,
                    content_type=a.content_type,
                    size_bytes=a.size_bytes,
                    created_at=a.created_at,
                )
                for a in items
            ],
        )
    finally:
        db.close()


@router.get("/bot/jobs/{job_id}/artifacts/{artifact_id}/download")
def download_artifact_for_job(job_id: UUID, artifact_id: UUID, chat_id: int):
    db = _get_db()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        delivery = db.query(models.Delivery).filter(models.Delivery.job_id == job_id).first()
        if not delivery:
            raise HTTPException(status_code=404, detail="Delivery not found")

        if int(delivery.chat_id) != int(chat_id):
            raise HTTPException(status_code=404, detail="Not Found")  # owner check (Variant A)

        a = db.query(models.Artifact).filter(models.Artifact.id == artifact_id).first()
        if not a:
            raise HTTPException(status_code=404, detail="Artifact not found")

        if a.doc_id != job.doc_id:
            raise HTTPException(status_code=404, detail="Not Found")  # artifact must belong to job

        return FileResponse(
            path=a.storage_path,
            media_type=a.content_type,
            filename=a.filename,
        )
    finally:
        db.close()


@router.get("/artifacts/{artifact_id}/download")
def download_artifact_deprecated(artifact_id: UUID):
    raise HTTPException(
        status_code=410,
        detail="Deprecated. Use /v1/bot/jobs/{job_id}/artifacts/{artifact_id}/download?chat_id=...",
    )
