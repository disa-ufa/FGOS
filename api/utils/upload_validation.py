from __future__ import annotations

from dataclasses import dataclass
from zipfile import ZipFile, BadZipFile
import io


@dataclass(frozen=True)
class DetectedFile:
    kind: str          # "pdf" | "docx"
    content_type: str  # mime
    ext: str           # ".pdf" | ".docx"


def detect_file_kind(data: bytes) -> DetectedFile:
    # PDF signature
    if data.startswith(b"%PDF-"):
        return DetectedFile(kind="pdf", content_type="application/pdf", ext=".pdf")

    # DOCX is a ZIP with required entries
    if data.startswith(b"PK\x03\x04"):
        try:
            with ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "[Content_Types].xml" in names and "word/document.xml" in names:
                    return DetectedFile(
                        kind="docx",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        ext=".docx",
                    )
        except BadZipFile:
            pass

    raise ValueError("Unsupported file signature (only DOCX/PDF are allowed)")