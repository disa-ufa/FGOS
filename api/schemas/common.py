from __future__ import annotations
from pydantic import BaseModel
from typing import Literal, Optional, List
from uuid import UUID
from datetime import datetime

JobStatus = Literal["QUEUED","RUNNING","DONE","FAILED"]

class UploadDocumentResponse(BaseModel):
    doc_id: UUID
    job_id: UUID
    status: JobStatus


class IssueEvidence(BaseModel):
    title: str
    score: Optional[int] = None
    page: Optional[int] = None
    block_id: Optional[str] = None
    quote: Optional[str] = None
    hint: Optional[str] = None

class JobSummary(BaseModel):
    total_score: Optional[float] = None
    max_score: Optional[float] = None
    top_issues: List[str] = []
    issues: List[IssueEvidence] = []

class JobStatusResponse(BaseModel):
    job_id: UUID
    doc_id: UUID
    status: JobStatus
    progress: int = 0
    error_message: Optional[str] = None
    needs_clarification: bool = False
    summary: Optional[JobSummary] = None
    updated_at: datetime

ArtifactKind = Literal["REPORT_PDF","HIGHLIGHTED_DOCX","HIGHLIGHTED_PDF","EXTRACT_JSON"]

class ArtifactItem(BaseModel):
    artifact_id: UUID
    doc_id: UUID
    kind: ArtifactKind
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime

class ArtifactsListResponse(BaseModel):
    doc_id: UUID
    items: List[ArtifactItem]

class PendingDeliveryItem(BaseModel):
    job_id: UUID
    doc_id: UUID
    chat_id: int
    status: JobStatus
    error_message: Optional[str] = None
    summary: Optional[JobSummary] = None
    artifacts: List[ArtifactItem] = []


class PendingDeliveriesResponse(BaseModel):
    items: List[PendingDeliveryItem]
