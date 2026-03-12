from __future__ import annotations
from pathlib import Path
import re

PATH = Path("worker/pipeline/noo_rules.py")

RESOLVE = r"""
def _resolve_selector(root, selector: str):
    \"\"\"Resolve selectors like 'a.b', 'a[*].b', 'a[0].b' against dict/list trees.

    Returns a flat list of resolved nodes (skips None).
    \"\"\"
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
""".lstrip()


def main():
    text = PATH.read_text(encoding="utf-8")

    if "def _resolve_selector(" in text:
        print("resolve_selector already exists, nothing to do")
        return

    anchor = "def evaluate_noo_rubric"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("Cannot find anchor: def evaluate_noo_rubric")

    new_text = text[:pos] + RESOLVE + "\n\n" + text[pos:]
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH}: added _resolve_selector()")

if __name__ == "__main__":
    main()
