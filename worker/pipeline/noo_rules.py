from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shared.models.evidence import EvidenceRef


def _infer_page_from_block_id(source: str, block_id: str) -> Optional[int]:
    """Infer PDF page from canonical block_id.

    Supported formats:
    - 'p001b0000' (page 1)
    - 'p00001' (page 1)
    - 'p00001b0000' (page 1)
    """
    if (source or "").lower() != "pdf":
        return None
    s = (block_id or "").strip()
    # p + zero-padded page + optional 'b...' suffix
    m = re.match(r"^p0*(\d+)(?:b\d+)?$", s, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        page = int(m.group(1))
        return page if page > 0 else None
    except Exception:
        return None
def _norm_lc(s: str) -> str:
    return (s or "").strip().lower()



_EV_CODE_TOKENS_RE = re.compile(
    r"\b(docker|compose|yaml|yml|json|python|alembic|celery|sha256|endpoint|repo|github|fastapi|sqlalchemy|redis|postgres)\b",
    flags=re.IGNORECASE,
)

def _ev_is_text_like(text: str) -> bool:
    """Heuristic filter to prefer natural-language fragments over code/config snippets."""
    t = (text or "").strip()
    if not t:
        return False

    # fenced code
    if "```" in t:
        return False

    # YAML/docker-compose common shapes
    if re.search(r"(?m)^\s*(services|version)\s*:\s*$", t):
        return False
    if re.search(r"(?m)^\s*-\s+\S+", t) and re.search(r"(?m)^\s*[A-Za-z0-9_.-]+\s*:\s*\S+", t):
        return False

    # token blacklist
    if _EV_CODE_TOKENS_RE.search(t):
        return False

    # paths like a/b/c or a\b\c
    if re.search(r"[\\/][\w\-\.]+[\\/]", t):
        return False

    # symbol-heavy configs/code
    symbols = re.findall(r"[{}\[\]<>;:=|`~$^*]+", t)
    sym_len = sum(len(s) for s in symbols)
    if len(t) >= 40 and (sym_len / max(1, len(t))) > 0.12:
        return False

    # Cyrillic sentence
    if re.search("[\u0400-\u04FF]{6,}", t):
        return True

    # no Cyrillic: allow only short neutral fragments
    return len(t) <= 60


def _make_evidence(source_format: str, block_id: str, quote: str, kind: str, hint: str | None = None) -> Dict[str, Any]:
    """Create an evidence dict compatible with shared.models.evidence.EvidenceRef."""
    return {
        "source": source_format,
        "page": _infer_page_from_block_id(source_format, block_id),
        "block_id": block_id,
        "start": None,
        "end": None,
        "quote": (quote or "").strip(),
        "hint": hint or kind,
    }


def _dedup_evidence(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate evidence snippets by (block_id, start, end, quote). Keeps first occurrence."""
    out: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        key = (
            it.get("block_id"),
            it.get("start"),
            it.get("end"),
            (it.get("quote") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _fallback_keywords(title: str | None, selectors: List[str]) -> List[str]:
    """Generate fallback keywords from criterion title and selectors."""
    out: List[str] = []
    if title:
        out.extend([w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", title)])
    for sel in selectors or []:
        base = sel.split(".")[-1]
        base = base.replace("[*]", "")
        base = re.sub(r"[^A-Za-z0-9_]", "", base)
        if base:
            out.append(base.lower())
    # uniq preserve order
    seen: set[str] = set()
    uniq: List[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq[:8]


def _node_has_value(node: Any) -> bool:
    """Return True if extracted node contains a meaningful value."""
    if node is None:
        return False
    if isinstance(node, dict):
        if "value" in node:
            v = node.get("value")
            if v is None:
                return False
            if isinstance(v, str):
                return bool(v.strip())
            if isinstance(v, (int, float, bool)):
                return True
            if isinstance(v, list):
                return any(_node_has_value(x) for x in v)
            if isinstance(v, dict):
                return _node_has_value(v)
            return True
        return any(_node_has_value(v) for v in node.values())
    if isinstance(node, str):
        return bool(node.strip())
    if isinstance(node, (int, float, bool)):
        return True
    if isinstance(node, list):
        return any(_node_has_value(x) for x in node)
    return False


def _gather_evidence(node: Any) -> List[Dict[str, Any]]:
    """Collect evidence items from extracted nodes (flat list)."""
    if node is None:
        return []
    if isinstance(node, list):
        out: List[Dict[str, Any]] = []
        for x in node:
            out.extend(_gather_evidence(x))
        return out
    if isinstance(node, dict):
        out: List[Dict[str, Any]] = []
        ev = node.get("evidence")
        if isinstance(ev, list):
            out.extend([e for e in ev if isinstance(e, dict)])
        if "value" in node:
            out.extend(_gather_evidence(node.get("value")))
        for k, v in node.items():
            if k in ("evidence", "value"):
                continue
            if isinstance(v, (dict, list)):
                out.extend(_gather_evidence(v))
        return out
    return []


def _resolve_selector(root: Any, selector: str) -> List[Any]:
    """Resolve selectors like 'a.b', 'a[*].b', 'a[0].b' against dict/list trees.

    Returns a flat list of resolved nodes (skips None).
    """
    if root is None:
        return []
    if not selector:
        return [root]

    parts = selector.split(".")
    cur: List[Any] = [root]
    token_re = re.compile(r"^(?P<name>[A-Za-z0-9_]+)(?:\[(?P<bracket>\*|\d+)\])?$")

    for part in parts:
        m = token_re.match(part.strip())
        if not m:
            return []
        name = m.group("name")
        bracket = m.group("bracket")

        nxt: List[Any] = []
        for obj in cur:
            if not isinstance(obj, dict):
                continue
            val = obj.get(name)
            if val is None:
                continue
            if bracket is None:
                nxt.append(val)
            elif bracket == "*":
                if isinstance(val, list):
                    nxt.extend([x for x in val if x is not None])
                else:
                    nxt.append(val)
            else:
                idx = int(bracket)
                if isinstance(val, list) and 0 <= idx < len(val) and val[idx] is not None:
                    nxt.append(val[idx])
        cur = nxt

    out: List[Any] = []
    for x in cur:
        if x is None:
            continue
        if isinstance(x, list):
            out.extend([y for y in x if y is not None])
        else:
            out.append(x)
    return out


def _keyword_evidence(
    blocks: List[Dict[str, Any]],
    source_format: str,
    keywords: List[str],
    hint: str | None = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    if not keywords:
        return []

    # Filter out too-short / noisy keywords
    kws: List[str] = []
    for k in keywords:
        if not k:
            continue
        k2 = k.strip().lower()
        if len(k2) < 4:
            continue
        if re.fullmatch(r"[0-9]+", k2):
            continue
        kws.append(k2)

    if not kws:
        return []

    candidates_text: List[Tuple[Dict[str, Any], str]] = []
    candidates_any: List[Tuple[Dict[str, Any], str]] = []

    for b in blocks:
        text = (b.get("text") or "")
        tlc = text.lower()
        if not tlc.strip():
            continue
        if any(k in tlc for k in kws):
            quote = text.strip().replace("\n", " ")
            if len(quote) > 240:
                quote = quote[:240] + "…"
            if _ev_is_text_like(text):
                candidates_text.append((b, quote))
            else:
                candidates_any.append((b, quote))

    evs: List[Dict[str, Any]] = []
    for (b, quote) in candidates_text[:limit]:
        evs.append(_make_evidence(source_format, b.get("block_id") or "", quote, "keywords"))
    if len(evs) < limit:
        for (b, quote) in candidates_any:
            if len(evs) >= limit:
                break
            evs.append(_make_evidence(source_format, b.get("block_id") or "", quote, "keywords_fallback"))

    return evs


def _resolve_selector(root, selector: str):
    """Resolve selectors like 'a.b', 'a[*].b', 'a[0].b' against dict/list trees.

    Returns a flat list of resolved nodes (skips None).
    """
    if root is None:
        return []
    if not selector:
        return [root]

    parts = selector.split(".")
    cur = [root]

    token_re = re.compile(r"^(?P<name>[A-Za-z0-9_]+)(?:\[(?P<bracket>\*|\d+)\])?$")

    for part in parts:
        m = token_re.match(part.strip())
        if not m:
            # unknown token -> no match
            return []
        name = m.group("name")
        bracket = m.group("bracket")

        nxt = []
        for obj in cur:
            if obj is None:
                continue

            if isinstance(obj, dict):
                val = obj.get(name)
            else:
                # if selector expects dict key but obj isn't dict
                continue

            if val is None:
                continue

            if bracket is None:
                nxt.append(val)
            elif bracket == "*":
                if isinstance(val, list):
                    nxt.extend([x for x in val if x is not None])
                else:
                    nxt.append(val)
            else:
                idx = int(bracket)
                if isinstance(val, list) and 0 <= idx < len(val):
                    if val[idx] is not None:
                        nxt.append(val[idx])

        cur = nxt

    # final flatten one level if list(s) remained
    out = []
    for x in cur:
        if x is None:
            continue
        if isinstance(x, list):
            out.extend([y for y in x if y is not None])
        else:
            out.append(x)
    return out


def _dedup_evidence(items):
    """Deduplicate evidence snippets by (block_id, start, end, text). Keeps first occurrence."""
    out = []
    seen = set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        key = (
            it.get("block_id"),
            it.get("start"),
            it.get("end"),
            (it.get("text") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _fallback_keywords(title: str | None, selectors: list[str]) -> list[str]:
    """Generate fallback keywords from criterion title and selectors.
    Used only when we have no evidence snippets yet.
    """
    out: list[str] = []
    if title:
        # take words >= 4 chars, lowercase
        out.extend([w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", title)])

    for sel in selectors or []:
        # selectors like 'stages[*].goal' -> goal
        base = sel.split(".")[-1]
        base = base.replace("[*]", "").replace("[0]", "")
        base = re.sub(r"[^A-Za-z0-9_]", "", base)
        if base:
            out.append(base.lower())

    # uniq, keep order
    seen = set()
    uniq: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq[:8]


def evaluate_noo_rubric(
    rubric: Dict[str, Any],
    canonical: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply rubric rules to extracted lesson-plan signals.

    This is a *heuristic* rule engine for MVP: no strict template is assumed.
    """
    blocks: List[Dict[str, Any]] = canonical.get("blocks") or []
    source_format = ((canonical.get("source") or {}).get("format")) or "docx"

    criteria_results: List[Dict[str, Any]] = []
    total_score = 0.0
    max_score = 0.0

    for crit in rubric.get("criteria") or []:
        # Rubric uses "criterion_id" (canonical). Keep backward-compat with older "id".
        crit_id = crit.get("criterion_id") or crit.get("id")
        title = crit.get("title")
        group = crit.get("group")
        weight = float(crit.get("weight") or 1.0)
        rule = crit.get("rule") or {}
        defaults = crit.get("defaults") or {}

        needs_evidence = bool(rule.get("needs_evidence"))
        required_fields_any: List[str] = list(rule.get("required_fields_any") or [])
        keywords_any: List[str] = list(rule.get("keywords_any") or [])
        min_present = rule.get("min_present")
        min_stage_count = rule.get("min_stage_count")

        present_fields = 0
        evs: List[Dict[str, Any]] = []

        # 1) fields-based evidence
        for sel in required_fields_any:
            nodes = _resolve_selector(extracted, sel)
            if any(_node_has_value(n) for n in nodes):
                present_fields += 1
                for n in nodes:
                    evs.extend(_gather_evidence(n))

        # 2) keywords-based evidence
        evs.extend(_keyword_evidence(blocks, source_format, keywords_any, limit=3, hint="keywords_any"))
        evs = _dedup_evidence(evs)

        # 2b) fallback evidence for header-like criteria (e.g., 'Паспорт урока')
        if not evs and required_fields_any:
            fb = _fallback_keywords(title, required_fields_any)
            if fb:
                evs.extend(_keyword_evidence(blocks, source_format, fb, limit=2, hint="fallback"))
                evs = _dedup_evidence(evs)

        # 2c) last-resort title-keyword search (kept small to avoid noise)
        if not evs and not keywords_any and title:
            tk = _title_keywords(str(title))
            if tk:
                evs.extend(_keyword_evidence(blocks, source_format, tk, limit=1, hint="title"))
                evs = _dedup_evidence(evs)

        # 3) condition evaluation
        cond = True
        if min_present is not None:
            cond = cond and (present_fields >= int(min_present))
        if min_stage_count is not None:
            stage_count = len(extracted.get("stages") or [])
            cond = cond and (stage_count >= int(min_stage_count))
        if (min_present is None and min_stage_count is None and required_fields_any):
            cond = cond and (present_fields >= 1)
        if (min_present is None and min_stage_count is None and not required_fields_any and keywords_any):
            cond = cond and bool(evs)

        # 4) scoring
        score: int
        if cond and (not needs_evidence or evs):
            score = 2
        elif cond or evs:
            score = 1
        else:
            score = 0

        if needs_evidence and score == 2 and not evs:
            score = 1

        if score == 0 and ("if_no_evidence_score" in defaults) and not evs:
            score = int(defaults.get("if_no_evidence_score") or 0)

        # cap
        score = max(0, min(2, score))

        criteria_results.append(
            {
                "id": crit_id,
                "title": title,
                "group": group,
                "weight": weight,
                "score": score,
                "evidence": evs,
                "debug": {
                    "present_fields": present_fields,
                    "needs_evidence": needs_evidence,
                    "required_fields_any": required_fields_any,
                    "keywords_any": keywords_any,
                },
            }
        )

        total_score += float(score) * weight
        max_score += 2.0 * weight

    # top issues: take the most critical misses first
    issues: List[str] = []
    for r in criteria_results:
        if int(r.get("score") or 0) < 2:
            issues.append(f"{r.get('title')}")

    # evidence for issues (for UI/bot messages)
    issues_with_evidence: List[Dict[str, Any]] = []
    by_title = {str(r.get("title")): r for r in criteria_results if r.get("title")}
    for title in issues[:7]:
        r = by_title.get(str(title))
        if not r:
            issues_with_evidence.append({"title": str(title)})
            continue
        evs = r.get("evidence") or []
        ev0 = evs[0] if isinstance(evs, list) and evs else {}
        issues_with_evidence.append(
            {
                "title": str(title),
                "score": int(r.get("score")) if r.get("score") is not None else None,
                "page": ev0.get("page"),
                "block_id": ev0.get("block_id"),
                "quote": ev0.get("quote"),
                "hint": ev0.get("hint"),
            }
        )

    return {
        "rubric_version": rubric.get("version"),
        "total_score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "top_issues": issues[:7],
        "issues": issues_with_evidence,
        "criteria": criteria_results,
    }




