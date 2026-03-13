from __future__ import annotations

import logging
import time

import json
import os
import uuid
import re
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from docx import Document as DocxDocument
from docx.document import Document as _DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from worker.celery_app import celery_app
from worker.config import settings
from worker.observability.logging import setup_logging as setup_worker_logging

from worker.observability.request_id import set_request_id, reset_request_id
from worker.observability.metrics import inc_job_status, observe_job_duration, observe_stage
from api.db.base import Base
from api.db import models
from api.storage.local import ensure_dir, path_for_artifacts
from api.utils.atomic_write import atomic_write_text

from shared.rubric.load import load_rubric
from worker.pipeline.noo_extract import extract_noo_from_canonical
from worker.pipeline.noo_rules import evaluate_noo_rubric
from worker.pipeline.report_noo import render_noo_report_pdf
from worker.parsers.pdf_to_canonical import parse_pdf_to_canonical

from worker.pipeline.highlight_docx import highlight_docx_copy

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

setup_worker_logging()
logger = logging.getLogger("fgos.worker.process")


_UUID_RE = re.compile(
    r"(?i)(?:urn:uuid:)?(?P<u>[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})"
)


def _coerce_uuid(value: object) -> uuid.UUID | None:
    """Best-effort UUID parser for Celery payloads.

    We may receive any of:
    - uuid.UUID
    - canonical string: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    - repr string: "UUID('...')"
    - bytes
    - dict-like serializer outputs
    """

    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value

    # Common serializer shapes
    if isinstance(value, dict):
        for k in ("uuid", "value", "id"):
            if k in value:
                return _coerce_uuid(value[k])

    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            value = bytes(value).decode("utf-8", errors="ignore")
        except Exception:
            value = str(value)

    s = str(value).strip()
    if not s:
        return None

    # Strip wrappers like UUID('...') and braces
    if s.startswith("UUID(") and s.endswith(")"):
        s = s[5:-1].strip().strip("\"'")
    s = s.strip().strip("{}")

    m = _UUID_RE.search(s)
    if not m:
        return None

    u = m.group("u")
    if "-" not in u and len(u) == 32:
        u = f"{u[0:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:32]}"
    try:
        return uuid.UUID(u)
    except Exception:
        return None


def _update_job(db, job: models.Job, **kwargs) -> None:
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(UTC)
    db.add(job)
    db.commit()


def _make_dummy_report(report_path: Path, doc_id: str, job_id: str, blocks_total: int) -> None:
    c = canvas.Canvas(str(report_path), pagesize=A4)
    c.setFont("Helvetica", 14)
    c.drawString(72, 800, "FGOS Helper (NOO) - MVP Report")
    c.setFont("Helvetica", 10)
    c.drawString(72, 780, f"doc_id: {doc_id}")
    c.drawString(72, 765, f"job_id: {job_id}")
    c.drawString(72, 750, f"parsed blocks: {blocks_total}")
    c.drawString(72, 740, "Pipeline is running in skeleton mode.")
    c.drawString(72, 725, "Next step: parsing DOCX/PDF, extracting fields, rule-checks, evidence highlighting.")
    c.showPage()
    c.save()


def _iter_docx_blocks(doc: _DocxDocument) -> Iterable[Paragraph | Table]:
    """Yield paragraphs and tables in document order."""
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def _parse_docx_to_canonical(docx_path: Path) -> Dict[str, Any]:
    """Parse .docx into a stable, minimal 'canonical' JSON for downstream checks.

    MVP goal: preserve order and provide block-level addressing.
    """
    d = DocxDocument(str(docx_path))

    blocks: List[Dict[str, Any]] = []
    p_index = -1
    t_index = -1

    for item in _iter_docx_blocks(d):
        if isinstance(item, Paragraph):
            p_index += 1
            text = (item.text or "").strip()

            style_name: Optional[str] = None
            try:
                style_name = item.style.name if item.style else None
            except Exception:
                style_name = None

            is_heading = bool(style_name) and (
                style_name.lower().startswith("heading")
                or "заголов" in style_name.lower()
            )
            if not text and not is_heading:
                continue

            b_type = "heading" if is_heading else "paragraph"
            blocks.append(
                {
                    "block_id": f"p{p_index:05d}",
                    "type": b_type,
                    "text": text,
                    "meta": {"p_index": p_index, "style": style_name},
                }
            )

        elif isinstance(item, Table):
            t_index += 1
            rows: List[List[str]] = []
            for row in item.rows:
                rows.append([(cell.text or "").strip() for cell in row.cells])

            table_text = "\n".join(["\t".join(r) for r in rows]).strip()

            blocks.append(
                {
                    "block_id": f"t{t_index:05d}",
                    "type": "table",
                    "text": table_text,
                    "meta": {"t_index": t_index, "rows": rows},
                }
            )

    return {
        "schema_version": 1,
        "source": {"format": "docx", "path": str(docx_path)},
        "blocks": blocks,
        "stats": {
            "blocks_total": len(blocks),
            "paragraphs_total": sum(1 for b in blocks if b["block_id"].startswith("p")),
            "tables_total": sum(1 for b in blocks if b["block_id"].startswith("t")),
        },
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _upsert_artifact(
    db,
    *,
    doc_id: uuid.UUID,
    kind: models.ArtifactKind,
    filename: str,
    content_type: str,
    storage_path: str,
) -> models.Artifact:
    p = Path(storage_path)
    size_bytes = p.stat().st_size
    now = datetime.now(UTC)
    existing = (
        db.query(models.Artifact)
        .filter(
            models.Artifact.doc_id == doc_id,
            models.Artifact.kind == kind,
            models.Artifact.filename == filename,
        )
        .first()
    )
    if existing:
        existing.content_type = content_type
        existing.size_bytes = size_bytes
        existing.storage_path = storage_path
        existing.created_at = now
        db.add(existing)
        return existing

    a = models.Artifact(
        doc_id=doc_id,
        kind=kind,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path=storage_path,
        created_at=now,
    )
    db.add(a)
    return a


@celery_app.task(name="process_document", bind=True)
def process_document(self, job_id: str):
    """Main worker task.

    P0 guarantees:
    - Idempotent for already DONE jobs.
    - Atomic writes for JSON/PDF artifacts.
    - Upsert artifacts/checks to avoid duplicates on retries.
    """
    db = SessionLocal()
    rid_token = None
    job: models.Job | None = None

    try:
        job_uuid_obj = _coerce_uuid(job_id)
        if not job_uuid_obj:
            logger.warning(
                "process_document: invalid job_id=%r (type=%s); ignoring without retry",
                job_id,
                type(job_id).__name__,
            )
            return

        job_uuid = job_uuid_obj

        job = db.query(models.Job).filter(models.Job.id == job_uuid).first()
        if not job:
            logger.warning("process_document: job not found for id=%s", job_uuid)
            return

        # Idempotency: do not re-process already finished jobs.
        if job.status == models.JobStatus.DONE:
            logger.info("process_document: job %s already DONE; skip", job_uuid)
            return

        _update_job(db, job, status=models.JobStatus.RUNNING, progress=10, error_message=None)

        doc = db.query(models.Document).filter(models.Document.id == job.doc_id).first()
        if not doc:
            _update_job(db, job, status=models.JobStatus.FAILED, progress=100, error_message="Document not found")
            return

        artifacts_dir = path_for_artifacts(settings.storage_dir, str(doc.id))
        ensure_dir(artifacts_dir)

        logger.info("process_document: start job=%s doc=%s mime=%s", job_uuid, doc.id, doc.mime_type)
        t_job0 = time.perf_counter()

        # -----------------
        # Stage: parse -> canonical
        # -----------------
        t_parse0 = time.perf_counter()
        if (
            doc.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or str(doc.storage_path).lower().endswith(".docx")
        ):
            canonical: Dict[str, Any] = _parse_docx_to_canonical(Path(doc.storage_path))
        elif (doc.mime_type == "application/pdf") or str(doc.storage_path).lower().endswith(".pdf"):
            canonical = parse_pdf_to_canonical(Path(doc.storage_path))
        else:
            canonical = {
                "schema_version": 1,
                "source": {"format": "unknown", "path": str(doc.storage_path), "mime_type": doc.mime_type},
                "blocks": [
                    {
                        "block_id": "p00000",
                        "type": "paragraph",
                        "text": "MVP: parsing for this format is not implemented yet.",
                        "meta": {},
                    }
                ],
                "stats": {"blocks_total": 1, "paragraphs_total": 1, "tables_total": 0},
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }

        t_parse_ms = (time.perf_counter() - t_parse0) * 1000.0
        observe_stage("parse", t_parse_ms / 1000.0)
        blocks_total = int((canonical.get("stats") or {}).get("blocks_total") or 0)
        pages_total = int((canonical.get("stats") or {}).get("pages_total") or 0)
        text_chars_total = int((canonical.get("stats") or {}).get("text_chars_total") or 0)
        if pages_total:
            logger.info(
                "process_document: parsed canonical blocks=%s pages=%s chars=%s (%.1fms)",
                blocks_total,
                pages_total,
                text_chars_total,
                t_parse_ms,
            )
        else:
            logger.info("process_document: parsed canonical blocks=%s (%.1fms)", blocks_total, t_parse_ms)

        # If PDF has parsing error or no extractable text, FAIL fast (no retries).
        if (canonical.get("source") or {}).get("format") == "pdf":
            src = canonical.get("source") or {}
            err = src.get("error")
            chars_total = int((canonical.get("stats") or {}).get("text_chars_total") or 0)
        
            if err:
                msg = f"PDF поврежден или не поддерживается: {err}"
                logger.warning("process_document: PDF parse error; failing: %s", msg)
                _update_job(db, job, status=models.JobStatus.FAILED, progress=100, error_message=msg)
                return
        
            if chars_total == 0:
                msg = "Не удалось извлечь текст из PDF (похоже на скан). Загрузите DOCX или PDF с текстовым слоем."
                logger.warning("process_document: PDF has no extractable text; failing: %s", msg)
                _update_job(db, job, status=models.JobStatus.FAILED, progress=100, error_message=msg, needs_clarification=True)
                return
        
            logger.info("process_document: PDF text detected chars_total=%s; continuing normal pipeline", chars_total)
        
        canonical_path = artifacts_dir / "canonical_noo.json"
        atomic_write_text(canonical_path, json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")

        t_extract0 = time.perf_counter()
        if getattr(job, "needs_clarification", False):
            extracted = {
                "schema_version": 1,
                "meta": {},
                "goals": [],
                "tasks": [],
                "stages": [],
                "equipment": [],
                "ud": [],
                "comments": [
                    {
                        "value": "PDF без извлекаемого текста (похоже на скан). Нужен 'текстовый PDF' или DOCX.",
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
                "stats": {"stages_total": 0},
            }
        else:
            extracted = extract_noo_from_canonical(canonical)
        t_extract_ms = (time.perf_counter() - t_extract0) * 1000.0
        observe_stage("extract", t_extract_ms / 1000.0)
        logger.info("process_document: extracted fields (%.1fms)", t_extract_ms)
        extracted_path = artifacts_dir / "extracted_noo.json"
        atomic_write_text(extracted_path, json.dumps(extracted, ensure_ascii=False, indent=2), encoding="utf-8")

        # Persist canonical in DB (idempotent update of latest record)
        prev = (
            db.query(models.Extraction)
            .filter(models.Extraction.doc_id == doc.id)
            .order_by(models.Extraction.version.desc())
            .first()
        )
        if prev:
            prev.canonical_json = json.dumps(canonical, ensure_ascii=False)
            prev.created_at = datetime.now(UTC)
            db.add(prev)
        else:
            extr = models.Extraction(
                doc_id=doc.id,
                version=1,
                canonical_json=json.dumps(canonical, ensure_ascii=False),
                created_at=datetime.now(UTC),
            )
            db.add(extr)
        db.commit()

        # Upsert JSON artifacts (avoid duplicates on retry)
        _upsert_artifact(
            db,
            doc_id=doc.id,
            kind=models.ArtifactKind.EXTRACT_JSON,
            filename="canonical_noo.json",
            content_type="application/json",
            storage_path=str(canonical_path),
        )
        _upsert_artifact(
            db,
            doc_id=doc.id,
            kind=models.ArtifactKind.EXTRACT_JSON,
            filename="extracted_noo.json",
            content_type="application/json",
            storage_path=str(extracted_path),
        )
        db.commit()

        _update_job(db, job, progress=40)

        # -----------------
        # Stage: rule-checks
        # -----------------
        t_rules0 = time.perf_counter()
        rubric = load_rubric(job.rubric_version)

        if getattr(job, "needs_clarification", False):
            # Build a full 'all zero' result to produce a meaningful report.
            try:
                max_score = float(sum(float(c.get("weight") or 1.0) for c in (rubric.get("criteria") or [])) * 2.0)
            except Exception:
                max_score = 0.0

            criteria = []
            for c in (rubric.get("criteria") or []):
                criteria.append(
                    {
                        "criterion_id": c.get("criterion_id"),
                        "group": c.get("group"),
                        "title": c.get("title"),
                        "weight": c.get("weight", 1.0),
                        "score": 0,
                        "evidence": [],
                        "note": "Текст в PDF не извлечён (похоже на скан).",
                    }
                )

            results_payload = {
                "rubric_version": (rubric.get("version") if isinstance(rubric, dict) else job.rubric_version),
                "total_score": 0.0,
                "max_score": max_score,
                "criteria": criteria,
                "top_issues": [
                    "PDF без извлекаемого текста (похоже на скан). Загрузите текстовый PDF или DOCX.",
                ],
            }
        else:
            results_payload = evaluate_noo_rubric(rubric=rubric, canonical=canonical, extracted=extracted)

        t_rules_ms = (time.perf_counter() - t_rules0) * 1000.0
        observe_stage("rules", t_rules_ms / 1000.0)
        logger.info(
            "process_document: rules total_score=%s/%s (%.1fms)",
            results_payload.get("total_score"),
            results_payload.get("max_score"),
            t_rules_ms,
        )
        results_payload["debug"] = {
            "canonical_blocks_total": canonical.get("stats", {}).get("blocks_total", 0),
            "canonical_pages_total": (canonical.get("stats") or {}).get("pages_total"),
            "canonical_text_chars_total": (canonical.get("stats") or {}).get("text_chars_total"),
            "stages_detected": (extracted.get("stats") or {}).get("stages_total"),
            "note": "Heuristic MVP checks. Improve extraction/rules for better accuracy.",
        }

        # Idempotent update: keep one latest check per (doc_id, rubric_version)
        chk = (
            db.query(models.Check)
            .filter(models.Check.doc_id == doc.id, models.Check.rubric_version == job.rubric_version)
            .order_by(models.Check.created_at.desc())
            .first()
        )
        if chk:
            chk.results_json = json.dumps(results_payload, ensure_ascii=False)
            chk.total_score = str(results_payload.get("total_score", 0.0))
            chk.max_score = str(results_payload.get("max_score", 0.0))
            chk.created_at = datetime.now(UTC)
            db.add(chk)
        else:
            chk = models.Check(
                doc_id=doc.id,
                rubric_version=job.rubric_version,
                results_json=json.dumps(results_payload, ensure_ascii=False),
                total_score=str(results_payload.get("total_score", 0.0)),
                max_score=str(results_payload.get("max_score", 0.0)),
                created_at=datetime.now(UTC),
            )
            db.add(chk)
        db.commit()

        _update_job(db, job, progress=70)

        # -----------------
        # Stage: report
        # -----------------
        t_report0 = time.perf_counter()
        report_path = artifacts_dir / "report_noo.pdf"
        report_tmp = artifacts_dir / f"report_noo.{uuid.uuid4().hex}.tmp.pdf"

        render_noo_report_pdf(
            out_path=str(report_tmp),
            doc_id=str(doc.id),
            job_id=str(job.id),
            canonical=canonical,
            extracted=extracted,
            results=results_payload,
        )
        os.replace(report_tmp, report_path)
        t_report_ms = (time.perf_counter() - t_report0) * 1000.0
        observe_stage("report", t_report_ms / 1000.0)
        try:
            size = report_path.stat().st_size
        except Exception:
            size = -1
        logger.info("process_document: report generated bytes=%s (%.1fms)", size, t_report_ms)

        _upsert_artifact(
            db,
            doc_id=doc.id,
            kind=models.ArtifactKind.REPORT_PDF,
            filename="Отчет_ФГОС_НОО.pdf",
            content_type="application/pdf",
            storage_path=str(report_path),
        )
        db.commit()

        # -----------------
        # Stage: highlighted DOCX artifact (mandatory for DOCX inputs)
        # -----------------
        if (canonical.get("source") or {}).get("format") == "docx":
            t_highlight0 = time.perf_counter()
            severity_by_block_id = _severity_map_from_results(results_payload)
            highlighted_path = artifacts_dir / "highlighted_noo.docx"
            highlighted_tmp = artifacts_dir / f"highlighted_noo.{uuid.uuid4().hex}.tmp.docx"

            highlight_stats = highlight_docx_copy(
                src_path=str(doc.storage_path),
                dst_path=str(highlighted_tmp),
                severity_by_block_id=severity_by_block_id,
                add_legend=True,
            )
            os.replace(highlighted_tmp, highlighted_path)

            _upsert_artifact(
                db,
                doc_id=doc.id,
                kind=models.ArtifactKind.HIGHLIGHTED_DOCX,
                filename="Конспект_ФГОС_НОО_подсветка.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                storage_path=str(highlighted_path),
            )
            db.commit()

            t_highlight_ms = (time.perf_counter() - t_highlight0) * 1000.0
            observe_stage("highlight", t_highlight_ms / 1000.0)
            logger.info(
                "process_document: highlighted DOCX generated blocks=%s par_runs=%s tbl_runs=%s (%.1fms)",
                highlight_stats.get("blocks_marked"),
                highlight_stats.get("paragraph_runs"),
                highlight_stats.get("table_runs"),
                t_highlight_ms,
            )

        logger.info("process_document: DONE job=%s", job_uuid)
        t_job_ms = (time.perf_counter() - t_job0) * 1000.0
        inc_job_status("DONE")
        observe_job_duration("DONE", t_job_ms / 1000.0)
        _update_job(db, job, status=models.JobStatus.DONE, progress=100, error_message=None)
    except Exception as e:
        # Retry with exponential-ish backoff. Mark FAILED only when giving up.
        try:
            max_retries = int(getattr(self, "max_retries", 3) or 3)
            retries = int(getattr(self.request, "retries", 0) or 0)
            will_retry = retries < max_retries
        except Exception:
            will_retry = False

        if job is not None:
            try:
                msg = str(e)
                if len(msg) > 1000:
                    msg = msg[:1000] + "…"
                if will_retry:
                    _update_job(db, job, status=models.JobStatus.RUNNING, error_message=msg)
                else:
                    t_job_ms = (time.perf_counter() - t_job0) * 1000.0
                    inc_job_status("FAILED")
                    observe_job_duration("FAILED", t_job_ms / 1000.0)
                    _update_job(db, job, status=models.JobStatus.FAILED, progress=100, error_message=msg)
            except Exception:
                pass

        if will_retry:
            logger.exception("process_document: error job=%s; will retry (%s/%s)", getattr(job, 'id', None), retries, max_retries)
            countdown = 10 * (2 ** retries)
            raise self.retry(exc=e, countdown=countdown)
        logger.exception("process_document: error job=%s; giving up", getattr(job, 'id', None))
        # give up
    finally:
        if rid_token is not None:
            reset_request_id(rid_token)
        db.close()


def _severity_map_from_issues(issues: list[dict]) -> dict[str, int]:
    """Build severity map from compact issues payload.

    score==0 -> severity 2 (RED)
    score==1 -> severity 1 (YELLOW)
    """
    out: dict[str, int] = {}
    for it in issues or []:
        bid = (it or {}).get("block_id")
        if not bid:
            continue
        try:
            score = float((it or {}).get("score", 0))
        except Exception:
            score = 0.0
        sev = 2 if score <= 0 else (1 if score < 2 else 0)
        if sev <= 0:
            continue
        bid = str(bid)
        out[bid] = max(sev, int(out.get(bid, 0)))
    return out


def _severity_map_from_results(results_payload: dict[str, Any]) -> dict[str, int]:
    """Build a DOCX highlight severity map from full rubric results.

    Prefer criterion-level evidence because it covers all failed/partial criteria,
    not just the compact top-issues subset used for bot messages.
    Falls back to the compact issues payload when criterion evidence is absent.
    """
    out: dict[str, int] = {}

    for crit in (results_payload.get("criteria") or []):
        if not isinstance(crit, dict):
            continue
        try:
            score = float(crit.get("score", 0))
        except Exception:
            score = 0.0
        sev = 2 if score <= 0 else (1 if score < 2 else 0)
        if sev <= 0:
            continue

        for ev in (crit.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            bid = ev.get("block_id")
            if not bid:
                continue
            bid = str(bid)
            out[bid] = max(sev, int(out.get(bid, 0)))

    if out:
        return out

    return _severity_map_from_issues(results_payload.get("issues") or [])
