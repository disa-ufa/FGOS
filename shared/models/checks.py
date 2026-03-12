from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
from .evidence import EvidenceRef

@dataclass
class CriterionResult:
    criterion_id: str
    score: int
    comment: str = ""
    evidence: List[EvidenceRef] = field(default_factory=list)

@dataclass
class CheckSummary:
    total_score: Optional[float] = None
    max_score: Optional[float] = None
    top_issues: List[str] = field(default_factory=list)
