from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (  # type: ignore
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)


def _try_register_fonts() -> dict[str, str]:
    """Register Cyrillic-capable fonts if present in the container.

    Returns mapping with keys: regular, bold.
    Falls back to Helvetica if registration fails.
    """

    # Debian slim + fonts-dejavu-core
    reg = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", reg))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold))
        return {"regular": "DejaVuSans", "bold": "DejaVuSans-Bold"}
    except Exception:
        return {"regular": "Helvetica", "bold": "Helvetica-Bold"}


def _fmt_score(score: Any) -> str:
    if score is None:
        return "—"
    try:
        return str(int(score))
    except Exception:
        return str(score)


def _fmt_weight(weight: Any) -> str:
    if weight is None:
        return "—"
    try:
        # keep compact
        w = float(weight)
        if abs(w - int(w)) < 1e-9:
            return str(int(w))
        return f"{w:.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(weight)


def _pick_issue_evidence(results: Dict[str, Any], limit: int = 7) -> List[Dict[str, Any]]:
    """Prefer worker-precomputed issues, fallback to top_issues titles."""
    issues = results.get("issues")
    if isinstance(issues, list) and issues:
        out: List[Dict[str, Any]] = []
        for it in issues[:limit]:
            if isinstance(it, dict) and it.get("title"):
                out.append(it)
        return out

    # fallback: try to enrich top_issues from criteria titles
    top = results.get("top_issues") or []
    if not isinstance(top, list):
        return []

    criteria = results.get("criteria") or []
    by_title: dict[str, Dict[str, Any]] = {}
    if isinstance(criteria, list):
        for c in criteria:
            if isinstance(c, dict) and c.get("title"):
                by_title[str(c["title"])] = c

    out = []
    for title in top[:limit]:
        t = str(title)
        c = by_title.get(t)
        if not c:
            out.append({"title": t})
            continue
        evs = c.get("evidence") or []
        ev0 = evs[0] if isinstance(evs, list) and evs else {}
        out.append(
            {
                "title": t,
                "score": c.get("score"),
                "page": ev0.get("page"),
                "block_id": ev0.get("block_id"),
                "quote": ev0.get("quote"),
                "hint": ev0.get("hint"),
            }
        )
    return out


def render_noo_report_pdf(
    out_path: str,
    doc_id: str,
    job_id: str,
    canonical: Dict[str, Any],
    extracted: Dict[str, Any],
    results: Dict[str, Any],
) -> None:
    """Generate a human-readable PDF report (P0).

    P0 goals:
    - Cyrillic-safe fonts
    - Clear structure: summary, criteria table, top issues with evidence
    - Robust on missing fields
    """

    fonts = _try_register_fonts()
    styles = getSampleStyleSheet()

    # Base styles
    styles["Normal"].fontName = fonts["regular"]
    styles["Normal"].fontSize = 10
    styles["Normal"].leading = 13

    h1 = ParagraphStyle(
        "H1",
        parent=styles["Normal"],
        fontName=fonts["bold"],
        fontSize=16,
        leading=20,
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Normal"],
        fontName=fonts["bold"],
        fontSize=12,
        leading=15,
        spaceBefore=8,
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Отчет FGOS Helper (ФГОС НОО)",
        author="FGOS Helper",
    )

    story: List[Any] = []

    # --- Header ---
    story.append(Paragraph("Отчет FGOS Helper — проверка конспекта по ФГОС НОО", h1))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Дата формирования: {ts}", small))
    story.append(Paragraph(f"doc_id: {doc_id}", small))
    story.append(Paragraph(f"job_id: {job_id}", small))
    if results.get("rubric_version"):
        story.append(Paragraph(f"rubric: {results.get('rubric_version')}", small))

    blocks_total = (canonical.get("stats") or {}).get("blocks_total")
    stages_total = (extracted.get("stats") or {}).get("stages_total")
    if blocks_total is not None or stages_total is not None:
        story.append(
            Paragraph(
                f"Блоков распознано: {blocks_total if blocks_total is not None else '—'}; "
                f"этапов выявлено: {stages_total if stages_total is not None else '—'}",
                small,
            )
        )
    story.append(Spacer(1, 6))

    # --- Summary ---
    total = results.get("total_score")
    max_score = results.get("max_score")
    summary_line = f"Итог: {total if total is not None else '—'} / {max_score if max_score is not None else '—'}"
    # percent if possible
    try:
        if total is not None and max_score:
            pct = float(total) / float(max_score) * 100.0
            summary_line += f" ({pct:.0f}%)"
    except Exception:
        pass
    story.append(Paragraph(summary_line, h2))

    # --- Extracted meta ---
    meta = extracted.get("meta") or {}
    if isinstance(meta, dict) and meta:
        story.append(Paragraph("Извлечённые данные", h2))
        for k, label in (
            ("topic", "Тема"),
            ("class_grade", "Класс"),
            ("lesson_type", "Тип урока"),
            ("teacher", "Учитель"),
        ):
            v = meta.get(k)
            if isinstance(v, dict):
                val = v.get("value")
            else:
                val = None
            if val:
                story.append(Paragraph(f"• {label}: {val}", styles["Normal"]))
        story.append(Spacer(1, 4))

    # --- Criteria table ---
    story.append(Paragraph("Оценка по критериям", h2))

    rows: List[List[Any]] = [["Группа", "Критерий", "Балл", "Вес"]]
    for r in (results.get("criteria") or []):
        if not isinstance(r, dict):
            continue
        group = str(r.get("group") or "—")
        title = str(r.get("title") or "—")
        score = _fmt_score(r.get("score"))
        weight = _fmt_weight(r.get("weight"))
        rows.append(
            [
                Paragraph(group, small),
                Paragraph(title, styles["Normal"]),
                Paragraph(score, small),
                Paragraph(weight, small),
            ]
        )

    table = Table(
        rows,
        colWidths=[30 * mm, 115 * mm, 14 * mm, 14 * mm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), fonts["bold"]),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("FONTNAME", (0, 1), (-1, -1), fonts["regular"]),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, (0, 0, 0)),
                ("LINEABOVE", (0, 1), (-1, 1), 0.2, (0, 0, 0)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [(1, 1, 1), (0.97, 0.97, 0.97)]),
            ]
        )
    )
    story.append(table)

    # --- Top issues with evidence ---
    issues = _pick_issue_evidence(results, limit=7)
    if issues:
        story.append(PageBreak())
        story.append(Paragraph("Основные замечания (с доказательствами)", h2))
        for it in issues:
            title = str(it.get("title") or "—")
            score = it.get("score")
            page = it.get("page")
            block_id = it.get("block_id")
            quote = it.get("quote")
            hint = it.get("hint")

            head = f"• {title}"
            if score is not None:
                head += f" (балл: {_fmt_score(score)})"
            story.append(Paragraph(head, styles["Normal"]))

            loc_parts: List[str] = []
            if page is not None:
                loc_parts.append(f"стр. {page}")
            if block_id:
                loc_parts.append(f"блок {block_id}")
            if loc_parts:
                story.append(Paragraph("Локация: " + ", ".join(loc_parts), small))

            if quote:
                story.append(Paragraph("Цитата: " + str(quote), small))
            if hint:
                story.append(Paragraph("Подсказка: " + str(hint), small))
            story.append(Spacer(1, 4))

    doc.build(story)
