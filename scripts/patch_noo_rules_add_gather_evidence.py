from __future__ import annotations
from pathlib import Path

PATH = Path("worker/pipeline/noo_rules.py")

HELPER = """
def _gather_evidence(node):
    \"\"\"Collect evidence items from extracted nodes.

    Extracted nodes often look like:
      {"value": ..., "confidence": 0.7, "evidence": [ ... ]}
    This function returns a flat list of evidence dicts.
    \"\"\"
    if node is None:
        return []

    if isinstance(node, list):
        out = []
        for x in node:
            out.extend(_gather_evidence(x))
        return out

    if isinstance(node, dict):
        out = []
        ev = node.get("evidence")
        if isinstance(ev, list):
            out.extend([e for e in ev if isinstance(e, dict)])

        # Sometimes evidence is nested under value
        if "value" in node:
            out.extend(_gather_evidence(node.get("value")))

        # Also check other fields just in case
        for k, v in node.items():
            if k in ("evidence", "value"):
                continue
            if isinstance(v, (dict, list)):
                out.extend(_gather_evidence(v))

        return out

    return []
""".lstrip()

def main():
    text = PATH.read_text(encoding="utf-8")
    if "def _gather_evidence(" in text:
        print("gather_evidence already exists, nothing to do")
        return

    anchor = "def evaluate_noo_rubric"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("Cannot find anchor: def evaluate_noo_rubric")

    new_text = text[:pos] + HELPER + "\n\n" + text[pos:]
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH}: added _gather_evidence()")

if __name__ == "__main__":
    main()
