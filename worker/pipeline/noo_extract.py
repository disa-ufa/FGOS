from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from shared.models.evidence import EvidenceRef


def _norm(s: str) -> str:
    return (s or "").strip()


def _norm_lc(s: str) -> str:
    return _norm(s).lower()


def _make_evidence(source: str, block_id: str, quote: str, hint: str = "") -> Dict[str, Any]:
    ev = EvidenceRef(source=source, block_id=block_id, quote=(quote or "").strip()[:500], hint=hint)
    return asdict(ev)


def _field(value: str, evidence: List[Dict[str, Any]], confidence: float = 0.6) -> Dict[str, Any]:
    return {
        "value": (value or "").strip(),
        "confidence": float(confidence),
        "evidence": evidence,
    }


def _split_lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _is_heading_block(block: Dict[str, Any]) -> bool:
    if block.get("type") == "heading":
        return True
    style = (((block.get("meta") or {}).get("style")) or "").lower()
    return style.startswith("heading") or ("заголов" in style)


def _match_inline_kv(line: str, keys: List[str]) -> Optional[Tuple[str, str]]:
    """Try to parse 'KEY: value' in a single line."""
    for k in keys:
        # allow separators : - – —
        m = re.search(rf"^\s*{re.escape(k)}\s*[:\-–—]\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            return k, m.group(1).strip()
    return None


def _collect_list_items(lines: List[str]) -> List[str]:
    items: List[str] = []
    for ln in lines:
        # bullets or numbered
        m = re.match(r"^(?:[-•*]|\d+[\).]|[IVX]+[\).])\s*(.+)$", ln)
        if m:
            items.append(m.group(1).strip())
        else:
            # keep full line if it looks like a short item
            if len(ln) <= 220:
                items.append(ln)
    # de-dup while preserving order
    seen = set()
    out: List[str] = []
    for x in items:
        k = _norm_lc(x)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def extract_noo_from_canonical(canonical: Dict[str, Any]) -> Dict[str, Any]:
    """Heuristic extraction for ФГОС НОО from canonical blocks.

    IMPORTANT: there is no strict lesson-plan template. We do "best-effort" based
    on headings and common Russian labels.
    """
    source_format = ((canonical.get("source") or {}).get("format")) or "docx"
    blocks: List[Dict[str, Any]] = canonical.get("blocks") or []

    meta: Dict[str, Any] = {}
    goals: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    didactic_task: Optional[Dict[str, Any]] = None
    planned_results_texts: List[Dict[str, Any]] = []
    stages: List[Dict[str, Any]] = []

    # quick global signals
    methods_global: List[Dict[str, Any]] = []
    forms_global: List[Dict[str, Any]] = []
    assignments_global: List[Dict[str, Any]] = []
    assessment_global: List[Dict[str, Any]] = []
    reflection_global: List[Dict[str, Any]] = []
    hygiene_global: List[Dict[str, Any]] = []

    # common keywords for signals
    METHODS_KW = [
        "беседа",
        "объяснен",
        "объяснение",
        "практическ",
        "практика",
        "исследован",
        "проект",
        "игра",
        "работа в парах",
        "работа в групп",
        "индивидуальн",
        "фронтальн",
    ]
    FORMS_KW = [
        "фронтальная",
        "фронтально",
        "групповая",
        "групповая работа",
        "в парах",
        "индивидуальная",
        "индивидуально",
    ]
    ASSIGN_KW = ["задание", "упражнение", "решите", "выполните", "работа", "самостоятельно"]
    ASSESS_KW = ["оцен", "критери", "самооцен", "взаимооцен", "провер"]
    REFLECT_KW = ["рефлек", "итог", "подвед", "самооцен"]
    HYGIENE_KW = ["физминут", "гимнастик", "осанка", "перерыв", "проветр"]

    # Section scanning state
    section: Optional[str] = None
    section_started_at: Optional[str] = None

    # Stage scanning state
    current_stage: Optional[Dict[str, Any]] = None
    current_stage_text_acc: List[str] = []
    current_stage_evidence: List[Dict[str, Any]] = []

    def finalize_stage():
        nonlocal current_stage, current_stage_text_acc, current_stage_evidence
        if not current_stage:
            return
        stage_text = "\n".join([t for t in current_stage_text_acc if t.strip()])
        stage_lc = stage_text.lower()

        # Fill stage-level signals (very rough)
        def stage_hits(kw_list: List[str]) -> bool:
            return any(k in stage_lc for k in kw_list)

        if stage_hits(METHODS_KW):
            current_stage["methods"].append(
                _field("Указаны методы/приёмы (эвристика)", current_stage_evidence[:1], 0.4)
            )
        if stage_hits(FORMS_KW):
            current_stage["forms"].append(
                _field("Указаны формы работы (эвристика)", current_stage_evidence[:1], 0.4)
            )
        if stage_hits(ASSIGN_KW):
            current_stage["assignments"].append(
                _field("Есть задания/упражнения (эвристика)", current_stage_evidence[:1], 0.4)
            )
        if stage_hits(ASSESS_KW):
            current_stage["assessment"].append(
                _field("Есть оценивание/проверка (эвристика)", current_stage_evidence[:1], 0.4)
            )
        if stage_hits(REFLECT_KW):
            current_stage["teacher_actions"].append(
                _field("Есть подведение итогов/рефлексия (эвристика)", current_stage_evidence[:1], 0.3)
            )

        stages.append(current_stage)
        current_stage = None
        current_stage_text_acc = []
        current_stage_evidence = []

    STAGE_HINTS = [
        "организацион",
        "актуализац",
        "постановк",
        "изучение",
        "объяснен",
        "закреплен",
        "практическ",
        "контроль",
        "самостоятель",
        "рефлек",
        "итог",
        "домашн",
        "этап",
        "ход урока",
    ]

    # Pass 1: scan blocks
    for b in blocks:
        block_id = b.get("block_id") or ""
        text = _norm(b.get("text") or "")
        if not text:
            continue

        lines = _split_lines(text)

        # Meta extraction (try on every block)
        for ln in lines:
            kv = _match_inline_kv(
                ln,
                keys=[
                    "Тема",
                    "Тема урока",
                    "Класс",
                    "Учитель",
                    "Тип урока",
                    "УМК",
                    "Учебник",
                    "Программа",
                    "КТП",
                ],
            )
            if not kv:
                continue
            key, value = kv
            if not value:
                continue
            # map keys
            if key.lower().startswith("тема") and "topic" not in meta:
                meta["topic"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.topic")], 0.8)
            elif key.lower().startswith("класс") and "class_grade" not in meta:
                meta["class_grade"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.class_grade")], 0.7)
            elif key.lower().startswith("учитель") and "teacher" not in meta:
                meta["teacher"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.teacher")], 0.7)
            elif key.lower().startswith("тип") and "lesson_type" not in meta:
                meta["lesson_type"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.lesson_type")], 0.6)
            elif key.lower().startswith("умк") and "umk" not in meta:
                meta["umk"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.umk")], 0.6)
            elif key.lower().startswith("учебник") and "textbook" not in meta:
                meta["textbook"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.textbook")], 0.6)
            elif key.lower().startswith("программа") and "program_reference" not in meta:
                meta["program_reference"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.program_reference")], 0.5)
            elif key.lower().startswith("ктп") and "ktp_reference" not in meta:
                meta["ktp_reference"] = _field(value, [_make_evidence(source_format, block_id, ln, "meta.ktp_reference")], 0.5)

        # Section start detection
        heading_text_lc = _norm_lc(text)
        if _is_heading_block(b):
            if "цель" in heading_text_lc:
                section = "goals"
                section_started_at = block_id
            elif "задач" in heading_text_lc:
                section = "tasks"
                section_started_at = block_id
            elif "планируем" in heading_text_lc or "результат" in heading_text_lc:
                section = "planned_results"
                section_started_at = block_id
            elif "ход урока" in heading_text_lc or "этап" in heading_text_lc:
                # we may still capture stage headings later
                section = "stages"
                section_started_at = block_id
            elif "рефлекс" in heading_text_lc:
                section = "reflection"
                section_started_at = block_id
            elif "оцен" in heading_text_lc:
                section = "assessment"
                section_started_at = block_id

        # Inline didactic task / goals / tasks
        for ln in lines:
            ln_lc = ln.lower()

            if didactic_task is None and ("дидактическая задача" in ln_lc or ln_lc.startswith("задача урока")):
                # capture after separator if possible
                m = re.search(r"(?:дидактическая задача|задача урока)\s*[:\-–—]\s*(.+)$", ln, flags=re.IGNORECASE)
                value = (m.group(1) if m else ln).strip()
                didactic_task = _field(value, [_make_evidence(source_format, block_id, ln, "didactic_task")], 0.7)

            # If goals/tasks are in the same line
            if section is None:
                if ln_lc.startswith("цель"):
                    m = re.search(r"^\s*цель\s*[:\-–—]\s*(.+)$", ln, flags=re.IGNORECASE)
                    if m and m.group(1).strip():
                        goals.append(_field(m.group(1).strip(), [_make_evidence(source_format, block_id, ln, "goals")], 0.6))
                if ln_lc.startswith("задачи"):
                    m = re.search(r"^\s*задачи\s*[:\-–—]\s*(.+)$", ln, flags=re.IGNORECASE)
                    if m and m.group(1).strip():
                        tasks.append(_field(m.group(1).strip(), [_make_evidence(source_format, block_id, ln, "tasks")], 0.6))

        # Section content capture
        if section in ("goals", "tasks", "planned_results"):
            # Collect list items from this block
            items = _collect_list_items(lines)
            if items:
                ev = [_make_evidence(source_format, block_id, (items[0] if items else text), f"section:{section}")]
                for it in items[:10]:
                    if section == "goals":
                        goals.append(_field(it, ev, 0.5))
                    elif section == "tasks":
                        tasks.append(_field(it, ev, 0.5))
                    else:
                        planned_results_texts.append(_field(it, ev, 0.4))

        # Stage detection
        # 1) explicit 'Этап ...' or 2) common stage hints used as a separate line
        # We prefer headings, but allow paragraphs too.
        for ln in lines:
            ln_lc = ln.lower()
            is_stage_line = False
            if ln_lc.startswith("этап"):
                is_stage_line = True
            elif any(h in ln_lc for h in STAGE_HINTS) and (len(ln) <= 120):
                # short line with known hint
                is_stage_line = True

            if is_stage_line:
                # if we already have a stage, finalize
                finalize_stage()
                current_stage = {
                    "name": _field(ln, [_make_evidence(source_format, block_id, ln, "stage.name")], 0.7),
                    "assignments": [],
                    "assessment": [],
                    "uuds": [],
                    "ict": [],
                    "forms": [],
                    "methods": [],
                    "teacher_actions": [],
                    "student_actions": [],
                }
                current_stage_text_acc = [text]
                current_stage_evidence = [_make_evidence(source_format, block_id, ln, "stage")]
                break
        else:
            # not started a new stage in this block
            if current_stage is not None:
                current_stage_text_acc.append(text)

        # Global signals extraction (very lightweight)
        text_lc = text.lower()
        if any(k in text_lc for k in METHODS_KW):
            methods_global.append(_field("methods", [_make_evidence(source_format, block_id, text[:200], "methods_global")], 0.3))
        if any(k in text_lc for k in FORMS_KW):
            forms_global.append(_field("forms", [_make_evidence(source_format, block_id, text[:200], "forms_global")], 0.3))
        if any(k in text_lc for k in ASSIGN_KW):
            assignments_global.append(_field("assignments", [_make_evidence(source_format, block_id, text[:200], "assignments_global")], 0.3))
        if any(k in text_lc for k in ASSESS_KW):
            assessment_global.append(_field("assessment", [_make_evidence(source_format, block_id, text[:200], "assessment_global")], 0.3))
        if any(k in text_lc for k in REFLECT_KW):
            reflection_global.append(_field("reflection", [_make_evidence(source_format, block_id, text[:200], "reflection_global")], 0.3))
        if any(k in text_lc for k in HYGIENE_KW):
            hygiene_global.append(_field("hygiene", [_make_evidence(source_format, block_id, text[:200], "hygiene")], 0.3))

    finalize_stage()

    # Planned results: split by personal/regulative/cognitive/communicative if present
    planned_results: Dict[str, Any] = {}
    if planned_results_texts:
        planned_results["raw"] = planned_results_texts[:30]
        raw_lc = "\n".join([x.get("value", "") for x in planned_results_texts]).lower()
        if "личност" in raw_lc:
            planned_results["personal"] = True
        if "регулятив" in raw_lc:
            planned_results["regulative"] = True
        if "познав" in raw_lc:
            planned_results["cognitive"] = True
        if "коммуник" in raw_lc:
            planned_results["communicative"] = True

    extracted: Dict[str, Any] = {
        "schema_version": 1,
        "fgos_level": "noo",
        "source_format": source_format,
        "meta": meta,
        "goals": goals[:20],
        "tasks": tasks[:30],
        "didactic_task": didactic_task,
        "planned_results": planned_results,
        "stages": stages,
        "assessment": assessment_global[:10],
        "reflection": reflection_global[:10],
        "hygiene": hygiene_global[:10],
        "methods_global": methods_global[:10],
        "forms_global": forms_global[:10],
        "assignments_global": assignments_global[:10],
        "stats": {
            "blocks_total": int((canonical.get("stats") or {}).get("blocks_total") or 0),
            "stages_total": len(stages),
            "goals_total": len(goals),
            "tasks_total": len(tasks),
        },
    }
    return extracted
