from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from docx import Document as DocxDocument
from docx.document import Document as _DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement


def _iter_docx_blocks(doc: _DocxDocument) -> Iterable[Paragraph | Table]:
    """Yield top-level paragraphs and tables in document order.

    IMPORTANT: This mirrors the canonical parser logic used in worker.tasks.process,
    so indices (pXXXXX / tXXXXX) line up with evidence block_ids.
    """
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def _block_index_from_id(block_id: str) -> Optional[Tuple[str, int]]:
    """Return ('p'|'t', index) from block id like p00012 or t00003."""
    s = (block_id or "").strip()
    if len(s) < 2:
        return None
    kind = s[0].lower()
    if kind not in ("p", "t"):
        return None
    digits = "".join(ch for ch in s[1:] if ch.isdigit())
    if not digits:
        return None
    try:
        return kind, int(digits)
    except Exception:
        return None


def _highlight_paragraph(par: Paragraph, color: WD_COLOR_INDEX) -> int:
    """Highlight all runs in the paragraph. Returns runs highlighted."""
    count = 0
    for r in par.runs:
        try:
            r.font.highlight_color = color
            count += 1
        except Exception:
            pass
    return count


def _highlight_table(tbl: Table, color: WD_COLOR_INDEX) -> int:
    count = 0
    for row in tbl.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                count += _highlight_paragraph(p, color)
    return count


def _insert_legend_at_top(doc: _DocxDocument, text: str) -> None:
    # Insert a simple paragraph at the beginning of the document body.
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    p.append(r)
    doc.element.body.insert(0, p)


def highlight_docx_copy(
    *,
    src_path: str,
    dst_path: str,
    severity_by_block_id: Dict[str, int],
    add_legend: bool = True,
) -> Dict[str, int]:
    """Create a highlighted DOCX copy.

    severity_by_block_id:
      2 -> strong issue (score 0) -> red highlight
      1 -> minor issue  (score 1) -> yellow highlight

    Returns stats dict: {'paragraph_runs': X, 'table_runs': Y, 'blocks_marked': Z}
    """
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    doc = DocxDocument(str(src))

    # Precompute sets of indices to highlight (best severity wins)
    p_sev: Dict[int, int] = {}
    t_sev: Dict[int, int] = {}

    for bid, sev in (severity_by_block_id or {}).items():
        parsed = _block_index_from_id(bid)
        if not parsed:
            continue
        kind, idx = parsed
        if kind == "p":
            p_sev[idx] = max(int(sev), int(p_sev.get(idx, 0)))
        else:
            t_sev[idx] = max(int(sev), int(t_sev.get(idx, 0)))

    # Highlight in top-level order, mirroring canonical indices.
    p_index = -1
    t_index = -1
    par_runs = 0
    tbl_runs = 0
    blocks_marked = 0

    for item in _iter_docx_blocks(doc):
        if isinstance(item, Paragraph):
            p_index += 1
            sev = int(p_sev.get(p_index, 0))
            if sev <= 0:
                continue
            color = WD_COLOR_INDEX.RED if sev >= 2 else WD_COLOR_INDEX.YELLOW
            par_runs += _highlight_paragraph(item, color)
            blocks_marked += 1

        elif isinstance(item, Table):
            t_index += 1
            sev = int(t_sev.get(t_index, 0))
            if sev <= 0:
                continue
            color = WD_COLOR_INDEX.RED if sev >= 2 else WD_COLOR_INDEX.YELLOW
            tbl_runs += _highlight_table(item, color)
            blocks_marked += 1

    if add_legend:
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        legend = (
            f"FGOS Helper: подсветка замечаний ({ts}). "
            "Красным — критично (0/2), жёлтым — частично (1/2)."
        )
        try:
            _insert_legend_at_top(doc, legend)
        except Exception:
            pass

    doc.save(str(dst))

    return {
        "paragraph_runs": int(par_runs),
        "table_runs": int(tbl_runs),
        "blocks_marked": int(blocks_marked),
    }