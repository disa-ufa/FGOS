from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from docx import Document as DocxDocument
from docx.document import Document as _DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


def _iter_docx_blocks(doc: _DocxDocument) -> Iterable[Paragraph | Table]:
    """Yield paragraphs and tables in document order."""
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)



def parse_docx_to_canonical(docx_path: Path) -> Dict[str, Any]:
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
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

