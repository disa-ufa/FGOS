from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Literal

SourceType = Literal["docx", "pdf"]

@dataclass
class EvidenceRef:
    source: SourceType
    page: Optional[int] = None
    block_id: Optional[str] = None
    start: Optional[int] = None
    end: Optional[int] = None
    quote: str = ""
    hint: str = ""
