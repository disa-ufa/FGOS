from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
import json
import re

from api.db.session import SessionLocal
from api.db import models
from api.schemas.common import JobStatusResponse, JobSummary, IssueEvidence
from api.security.service_auth import require_service_auth

router = APIRouter(prefix="/v1", tags=["jobs"], dependencies=[Depends(require_service_auth)])


def _get_db() -> Session:
    return SessionLocal()


_PAGE_RE = re.compile(r"^p(?P<page>\d+)", flags=re.IGNORECASE)


def _page_from_block_id(block_id: str | None):
    """Best-effort: infer page number from block_id.

    Supported formats (best-effort):
      - p00001
      - p001b0000
      - p00001b0000

    Returns int page (1-based) or None.
    """

    if not block_id:
        return None

    s = str(block_id).strip()
    m = _PAGE_RE.match(s)
    if not m:
        return None

    try:
        return int(m.group("page"))
    except Exception:
        return None


def _normalize_page(page, block_id: str | None):
    if page is None:
        return _page_from_block_id(block_id)
    try:
        return int(page)
    except Exception:
        return _page_from_block_id(block_id)


def _issues_from_results(payload: dict) -> list[IssueEvidence]:
    """Extract evidence for top issues from worker results payload."""

    issues: list[IssueEvidence] = []
    try:
        raw_issues = payload.get("issues")
        if isinstance(raw_issues, list) and raw_issues:
            for it in raw_issues[:7]:
                if not isinstance(it, dict) or not it.get("title"):
                    continue

                block_id = it.get("block_id")
                page = _normalize_page(it.get("page"), block_id)

                issues.append(
                    IssueEvidence(
                        title=str(it.get("title")),
                        score=int(it.get("score")) if it.get("score") is not None else None,
                        page=page,
                        block_id=block_id,
                        quote=it.get("quote"),
                        hint=it.get("hint"),
                    )
                )
            return issues

        top = list(payload.get("top_issues") or [])[:7]
        criteria = payload.get("criteria") or []
        by_title = {str(c.get("title")): c for c in criteria if isinstance(c, dict) and c.get("title")}

        for title in top:
            c = by_title.get(str(title))
            if not c:
                issues.append(IssueEvidence(title=str(title)))
                continue

            evs = c.get("evidence") or []
            ev0 = evs[0] if isinstance(evs, list) and evs else {}

            block_id = ev0.get("block_id")
            page = _normalize_page(ev0.get("page"), block_id)

            issues.append(
                IssueEvidence(
                    title=str(title),
                    score=int(c.get("score")) if c.get("score") is not None else None,
                    page=page,
                    block_id=block_id,
                    quote=ev0.get("quote"),
                    hint=ev0.get("hint"),
                )
            )

    except Exception:
        return []

    return issues


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: UUID, chat_id: int):
    db = _get_db()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Object-level auth: job must belong to the same chat_id via Delivery.
        delivery = db.query(models.Delivery).filter(models.Delivery.job_id == job_id).first()
        if not delivery or int(delivery.chat_id) != int(chat_id):
            raise HTTPException(status_code=404, detail="Not Found")

        summary = None
        if job.status == models.JobStatus.DONE:
            chk = (
                db.query(models.Check)
                .filter(models.Check.doc_id == job.doc_id)
                .order_by(models.Check.created_at.desc())
                .first()
            )
            if chk and chk.results_json:
                try:
                    payload = json.loads(chk.results_json)
                    summary = JobSummary(
                        total_score=float(payload.get("total_score")) if payload.get("total_score") is not None else None,
                        max_score=float(payload.get("max_score")) if payload.get("max_score") is not None else None,
                        top_issues=payload.get("top_issues", []) or [],
                        issues=_issues_from_results(payload),
                    )
                except Exception:
                    summary = JobSummary(top_issues=[])

        return JobStatusResponse(
            job_id=job.id,
            doc_id=job.doc_id,
            status=job.status.value,
            progress=job.progress,
            error_message=job.error_message,
            needs_clarification=job.needs_clarification,
            summary=summary,
            updated_at=job.updated_at or datetime.utcnow(),
        )
    finally:
        db.close()
