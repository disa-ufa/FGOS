from __future__ import annotations
from pathlib import Path

PATH = Path("worker/pipeline/noo_rules.py")

HELPER = """
def _node_has_value(node) -> bool:
    \"\"\"Return True if extracted node contains a meaningful value.\"\"\"
    if node is None:
        return False

    # Typical extracted nodes: {"value": ..., "confidence": ..., "evidence": [...]}
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
        # If dict has any meaningful field at all
        for _, v in node.items():
            if _node_has_value(v):
                return True
        return False

    if isinstance(node, str):
        return bool(node.strip())
    if isinstance(node, (int, float, bool)):
        return True
    if isinstance(node, list):
        return any(_node_has_value(x) for x in node)

    return False
""".lstrip()

def main():
    text = PATH.read_text(encoding="utf-8")
    if "def _node_has_value(" in text:
        print("node_has_value already exists, nothing to do")
        return

    anchor = "def evaluate_noo_rubric"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("Cannot find anchor: def evaluate_noo_rubric")

    new_text = text[:pos] + HELPER + "\n\n" + text[pos:]
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH}: added _node_has_value()")

if __name__ == "__main__":
    main()
