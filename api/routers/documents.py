from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from api.config import settings
from api.db.session import SessionLocal
from api.db import models
from api.storage.local import ensure_dir, path_for_doc, path_for_artifacts
from api.schemas.common import UploadDocumentResponse
from api.security.service_auth import require_service_auth
from api.utils.upload_validation import detect_file_kind

router = APIRouter(prefix="/v1", tags=["documents"], dependencies=[Depends(require_service_auth)])


def _get_db() -> Session:
    return SessionLocal()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _safe_name(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    name = Path(name).name
    if len(name) > 120:
        name = name[-120:]
    return name or fallback


@router.post("/documents", response_model=UploadDocumentResponse)
def upload_document(
    telegram_user_id: int = Form(...),
    chat_id: int = Form(...),
    file: UploadFile = File(...),
):
    # Read with size limit (protect memory/DoS)
    max_bytes = settings.max_upload_bytes
    data = file.file.read(max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large. Max {settings.max_upload_mb} MB")

    # Detect by signature (do NOT trust content_type)
    try:
        detected = detect_file_kind(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    doc_id = uuid.uuid4()
    job_id = uuid.uuid4()

    sha = hashlib.sha256(data).hexdigest()
    size_bytes = len(data)

    doc_dir = path_for_doc(settings.storage_dir, str(doc_id))
    ensure_dir(doc_dir)
    ensure_dir(path_for_artifacts(settings.storage_dir, str(doc_id)))

    storage_path = doc_dir / f"original{detected.ext}"
    storage_path.write_bytes(data)

    db = _get_db()
    try:
        # 1) Ensure user
        user = db.query(models.User).filter(models.User.telegram_user_id == telegram_user_id).first()
        if not user:
            user = models.User(telegram_user_id=telegram_user_id)
            db.add(user)
            db.flush()

        # 2) Document
        doc = models.Document(
            id=doc_id,
            user_id=user.id,
            telegram_chat_id=chat_id,
            original_filename=_safe_name(file.filename, f"original{detected.ext}"),
            mime_type=detected.content_type,
            size_bytes=size_bytes,
            sha256=sha,
            storage_path=str(storage_path),
            created_at=_utcnow(),
        )
        db.add(doc)
        db.flush()

        # 3) Job
        job = models.Job(
            id=job_id,
            doc_id=doc_id,
            status=models.JobStatus.QUEUED,
            progress=0,
            rubric_version="noo_v1",
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(job)
        db.flush()

        # Persist doc+job first
        db.commit()

        # 4) ENQUEUE IS CRITICAL:
        # If broker is down -> do NOT leave QUEUED hanging.
        try:
            from api.celery_app import celery_app
            celery_app.send_task("process_document", args=[str(job_id)])
        except Exception as e:
            # Mark job FAILED (best-effort)
            try:
                job.status = models.JobStatus.FAILED
                job.error_message = f"enqueue failed: {type(e).__name__}"
                job.updated_at = _utcnow()
                db.commit()
            except Exception:
                db.rollback()

            # Do NOT create Delivery, return FAILED
            return UploadDocumentResponse(doc_id=doc_id, job_id=job_id, status="FAILED")

        # 5) Delivery should exist ONLY if task was enqueued successfully
        try:
            delivery = models.Delivery(
                job_id=job_id,
                chat_id=chat_id,
                delivered_at=None,
                created_at=_utcnow(),
            )
            db.add(delivery)
            db.commit()
        except Exception:
            # Best-effort: job still processes even if delivery insert fails
            db.rollback()

    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database integrity error") from e
    except (OperationalError, ProgrammingError) as e:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Database schema is not ready. Run migrations (alembic upgrade head).",
        ) from e
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return UploadDocumentResponse(doc_id=doc_id, job_id=job_id, status="QUEUED")