from __future__ import annotations
from pathlib import Path
import re

PATH = Path("worker/pipeline/noo_rules.py")

HELPER = """
def _fallback_keywords(title: str | None, selectors: list[str]) -> list[str]:
    \"\"\"Generate fallback keywords from criterion title and selectors.
    Used only when we have no evidence snippets yet.
    \"\"\"
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
""".lstrip()

def main():
    text = PATH.read_text(encoding="utf-8")
    if "def _fallback_keywords(" in text:
        print("fallback_keywords already exists, nothing to do")
        return

    anchor = "def evaluate_noo_rubric"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("Cannot find anchor: def evaluate_noo_rubric")

    new_text = text[:pos] + HELPER + "\n\n" + text[pos:]
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH}: added _fallback_keywords()")

if __name__ == "__main__":
    main()
