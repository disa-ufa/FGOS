from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader


def parse_pdf_to_canonical(pdf_path: Path, max_pages: int = 200) -> Dict[str, Any]:
    """Parse a *text* PDF into canonical blocks.

    Notes:
    - This does NOT perform OCR. If a PDF is scanned (images only), extracted text
      will be empty and the caller should handle the 'no text' case.
    - We keep the representation close to DOCX canonical to reuse extract/rules.
    - block_id encodes page: p{page:03d}b{idx:04d}
    """
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        return {
            "schema_version": 1,
            "source": {"format": "pdf", "path": str(pdf_path), "error": str(e)},
            "blocks": [],
            "stats": {
                "pages_total": 0,
                "blocks_total": 0,
                "paragraphs_total": 0,
                "tables_total": 0,
                "text_chars_total": 0,
            },
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    pages_total = min(len(reader.pages), int(max_pages))

    blocks: List[Dict[str, Any]] = []
    text_chars_total = 0

    for pi in range(pages_total):
        page_no = pi + 1
        try:
            raw = reader.pages[pi].extract_text() or ""
        except Exception:
            raw = ""

        raw = raw.replace("\r", "\n")
        raw = re.sub(r"\n{3,}", "\n\n", raw).strip()

        # Split into paragraphs by blank lines
        paras = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]

        # Fallback: if no paragraphs but there are lines, join them
        if not paras:
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if lines:
                paras = [" ".join(lines)]

        for bi, para in enumerate(paras):
            text_chars_total += len(para)
            blocks.append(
                {
                    "block_id": f"p{page_no:03d}b{bi:04d}",
                    "type": "paragraph",
                    "text": para,
                    "meta": {"page": page_no, "para_index": bi},
                }
            )

    return {
        "schema_version": 1,
        "source": {"format": "pdf", "path": str(pdf_path)},
        "blocks": blocks,
        "stats": {
            "pages_total": pages_total,
            "blocks_total": len(blocks),
            "paragraphs_total": len(blocks),
            "tables_total": 0,
            "text_chars_total": int(text_chars_total),
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
