from __future__ import annotations
from pathlib import Path

PATH = Path("worker/pipeline/noo_rules.py")

HELPER = """
def _dedup_evidence(items):
    \"\"\"Deduplicate evidence snippets by (block_id, start, end, text). Keeps first occurrence.\"\"\"
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
""".lstrip()

def main():
    text = PATH.read_text(encoding="utf-8")
    if "def _dedup_evidence(" in text:
        print("dedup already exists, nothing to do")
        return

    anchor = "def evaluate_noo_rubric"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("Cannot find anchor: def evaluate_noo_rubric")

    new_text = text[:pos] + HELPER + "\n\n" + text[pos:]
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH}: added _dedup_evidence()")

if __name__ == "__main__":
    main()
