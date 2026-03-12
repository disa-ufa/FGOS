from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from datetime import datetime
import json

from api.db.session import SessionLocal
from api.db import models
from api.schemas.common import PendingDeliveriesResponse, PendingDeliveryItem, ArtifactItem, JobSummary, IssueEvidence
from api.security.service_auth import require_service_auth

router = APIRouter(prefix="/v1/bot", tags=["bot"], dependencies=[Depends(require_service_auth)])


def _get_db() -> Session:
    return SessionLocal()


def _issues_from_results(payload: dict) -> list[IssueEvidence]:
    issues: list[IssueEvidence] = []
    try:
        # Prefer precomputed issues (worker PR-08)
        raw_issues = payload.get("issues")
        if isinstance(raw_issues, list) and raw_issues:
            for it in raw_issues[:7]:
                if not isinstance(it, dict) or not it.get("title"):
                    continue
                issues.append(
                    IssueEvidence(
                        title=str(it.get("title")),
                        score=int(it.get("score")) if it.get("score") is not None else None,
                        page=int(it.get("page")) if it.get("page") is not None else None,
                        block_id=it.get("block_id"),
                        quote=it.get("quote"),
                        hint=it.get("hint"),
                    )
                )
            return issues

        top = list(payload.get("top_issues") or [])[:7]
        criteria = payload.get("criteria") or []
        by_title = {}
        for c in criteria:
            if isinstance(c, dict) and c.get("title"):
                by_title[str(c.get("title"))] = c

        for title in top:
            c = by_title.get(title)
            if not c:
                issues.append(IssueEvidence(title=str(title)))
                continue

            evs = c.get("evidence") or []
            ev0 = evs[0] if isinstance(evs, list) and evs else {}
            issues.append(
                IssueEvidence(
                    title=str(title),
                    score=int(c.get("score")) if c.get("score") is not None else None,
                    page=int(ev0.get("page")) if ev0.get("page") is not None else None,
                    block_id=ev0.get("block_id"),
                    quote=ev0.get("quote"),
                    hint=ev0.get("hint"),
                )
            )
    except Exception:
        return []
    return issues


def _build_summary_from_check(chk: models.Check | None) -> JobSummary | None:
    """Build JobSummary from the latest Check row (if any)."""

    if not chk or not chk.results_json:
        return None
    try:
        payload = json.loads(chk.results_json)
        return JobSummary(
            total_score=float(payload.get("total_score")) if payload.get("total_score") is not None else None,
            max_score=float(payload.get("max_score")) if payload.get("max_score") is not None else None,
            top_issues=payload.get("top_issues", []) or [],
            issues=_issues_from_results(payload),
        )
    except Exception:
        return JobSummary(top_issues=[])


@router.get("/pending-deliveries", response_model=PendingDeliveriesResponse)
def pending_deliveries(limit: int = 20):
    db = _get_db()
    try:
        q = (
            db.query(models.Delivery, models.Job, models.Document)
            .join(models.Job, models.Job.id == models.Delivery.job_id)
            .join(models.Document, models.Document.id == models.Job.doc_id)
            .filter(and_(models.Job.status.in_([models.JobStatus.DONE, models.JobStatus.FAILED]), models.Delivery.delivered_at.is_(None)))
            .order_by(models.Job.updated_at.asc())
            .limit(limit)
        )

        items = []
        for d, job, doc in q.all():
            artifacts = db.query(models.Artifact).filter(models.Artifact.doc_id == doc.id).all()
            chk = (
                db.query(models.Check)
                .filter(models.Check.doc_id == doc.id)
                .order_by(models.Check.created_at.desc())
                .first()
            )

            summary = _build_summary_from_check(chk)

            items.append(
                PendingDeliveryItem(
                    job_id=job.id,
                    doc_id=doc.id,
                    chat_id=d.chat_id,
                    status=job.status,
                    error_message=job.error_message,
                    summary=summary,
                    artifacts=[
                        ArtifactItem(
                            artifact_id=a.id,
                            doc_id=a.doc_id,
                            kind=a.kind.value,
                            filename=a.filename,
                            content_type=a.content_type,
                            size_bytes=a.size_bytes,
                            created_at=a.created_at,
                        )
                        for a in artifacts
                    ],
                )
            )
        return PendingDeliveriesResponse(items=items)
    finally:
        db.close()


@router.post("/deliveries/{job_id}/ack")
def ack_delivery(job_id: UUID):
    """Mark a delivery as delivered.

    Security: service-auth only. Returns 404 if delivery does not exist
    (do not leak whether a job_id exists; Variant A).
    """

    db = _get_db()
    try:
        d = db.query(models.Delivery).filter(models.Delivery.job_id == job_id).first()
        if not d:
            raise HTTPException(status_code=404, detail="Not Found")
        d.delivered_at = datetime.utcnow()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("/jobs/{job_id}", response_model=PendingDeliveryItem)
def bot_job(job_id: UUID, chat_id: int):
    """Fetch a single job details for a chat (service-auth protected).

    Useful for debugging/ops (and can be used by the bot as well).
    Security: job must exist AND belong to the same chat_id in deliveries.
    """

    db = _get_db()
    try:
        d = db.query(models.Delivery).filter(models.Delivery.job_id == job_id).first()
        if not d or d.chat_id != chat_id:
            raise HTTPException(status_code=404, detail="Not Found")

        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Not Found")

        doc = db.query(models.Document).filter(models.Document.id == job.doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Not Found")

        artifacts = db.query(models.Artifact).filter(models.Artifact.doc_id == doc.id).all()
        chk = (
            db.query(models.Check)
            .filter(models.Check.doc_id == doc.id)
            .order_by(models.Check.created_at.desc())
            .first()
        )
        summary = _build_summary_from_check(chk)

        return PendingDeliveryItem(
            job_id=job.id,
            doc_id=doc.id,
            chat_id=d.chat_id,
            status=job.status,
            error_message=job.error_message,
            summary=summary,
            artifacts=[
                ArtifactItem(
                    artifact_id=a.id,
                    doc_id=a.doc_id,
                    kind=a.kind.value,
                    filename=a.filename,
                    content_type=a.content_type,
                    size_bytes=a.size_bytes,
                    created_at=a.created_at,
                )
                for a in artifacts
            ],
        )
    finally:
        db.close()
