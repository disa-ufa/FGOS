from __future__ import annotations
from pathlib import Path

PATH = Path("worker/pipeline/noo_rules.py")

HELPER = """
def _make_evidence(source_format: str, block_id: str, text: str, kind: str, hint: str | None = None):
    \"\"\"Create a unified evidence record.\"\"\"
    return {
        "source_format": source_format,
        "block_id": block_id,
        "text": (text or "").strip(),
        "kind": kind,
        "hint": hint,
        "start": None,
        "end": None,
        "page": None,
    }
""".lstrip()

def main():
    text = PATH.read_text(encoding="utf-8")
    if "def _make_evidence(" in text:
        print("make_evidence already exists, nothing to do")
        return

    anchor = "def evaluate_noo_rubric"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("Cannot find anchor: def evaluate_noo_rubric")

    new_text = text[:pos] + HELPER + "\n\n" + text[pos:]
    # fix mojibake ellipsis if present
    new_text = new_text.replace("вЂ¦", "…")
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH}: added _make_evidence()")

if __name__ == "__main__":
    main()
