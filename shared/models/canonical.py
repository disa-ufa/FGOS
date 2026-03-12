from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .evidence import EvidenceRef

@dataclass
class ExtractedField:
    value: str
    confidence: float = 0.0
    evidence: List[EvidenceRef] = field(default_factory=list)

@dataclass
class LessonStage:
    name: ExtractedField = field(default_factory=lambda: ExtractedField(value=""))
    assignments: List[ExtractedField] = field(default_factory=list)
    assessment: List[ExtractedField] = field(default_factory=list)
    uuds: List[ExtractedField] = field(default_factory=list)
    ict: List[ExtractedField] = field(default_factory=list)
    forms: List[ExtractedField] = field(default_factory=list)
    methods: List[ExtractedField] = field(default_factory=list)
    teacher_actions: List[ExtractedField] = field(default_factory=list)
    student_actions: List[ExtractedField] = field(default_factory=list)

@dataclass
class LessonPlanCanonical:
    meta: Dict[str, Any] = field(default_factory=dict)
    goals: List[ExtractedField] = field(default_factory=list)
    tasks: List[ExtractedField] = field(default_factory=list)
    didactic_task: Optional[ExtractedField] = None
    planned_results: Dict[str, Any] = field(default_factory=dict)
    stages: List[LessonStage] = field(default_factory=list)
    assessment: List[ExtractedField] = field(default_factory=list)
    reflection: List[ExtractedField] = field(default_factory=list)
    hygiene: List[ExtractedField] = field(default_factory=list)
