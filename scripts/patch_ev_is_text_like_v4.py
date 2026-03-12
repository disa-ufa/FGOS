from __future__ import annotations
from pathlib import Path

PATH = Path("worker/pipeline/noo_rules.py")

FUNC = """
def _ev_is_text_like(text: str) -> bool:
    \"\"\"Heuristic filter to prefer natural-language fragments over code/config snippets.\"\"\"
    t = (text or "").strip()
    if not t:
        return False

    # YAML/docker-compose common shapes
    if re.search(r"(?m)^\\s*(services|version)\\s*:\\s*$", t):
        return False
    if re.search(r"(?m)^\\s*-\\s+\\S+", t) and re.search(r"(?m)^\\s*[A-Za-z0-9_.-]+\\s*:\\s*\\S+", t):
        return False

    # Token blacklist (config/infra/dev words)
    if re.search(r"\\b(docker|compose|yaml|yml|json|python|alembic|celery|sha256|endpoint|repo|github|fastapi|sqlalchemy|redis|postgres|postgresql|database_url|env|environment)\\b", t, flags=re.IGNORECASE):
        return False

    # Paths like a/b/c or a\\b\\c
    if re.search(r"[\\\\/][\\w\\-\\.]+[\\\\/]", t):
        return False

    # Symbol-heavy configs/code
    symbols = re.findall(r"[{}\\[\\]<>;:=|`~$^*]+", t)
    sym_len = sum(len(s) for s in symbols)
    if len(t) >= 40 and (sym_len / max(1, len(t))) > 0.12:
        return False

    # Cyrillic sentence (IMPORTANT: normal string, so \\uXXXX becomes real chars)
    if re.search("[\\u0400-\\u04FF]{6,}", t):
        return True

    # No Cyrillic: allow only short neutral fragments
    return len(t) <= 60
""".lstrip()

def main():
    text = PATH.read_text(encoding="utf-8")

    start = text.find("def _ev_is_text_like")
    if start < 0:
        raise SystemExit("Cannot find: def _ev_is_text_like")

    end = text.find("\ndef _keyword_evidence", start)
    if end < 0:
        raise SystemExit("Cannot find: def _keyword_evidence (anchor)")

    new_text = text[:start] + FUNC + "\n" + text[end+1:]  # keep leading newline before def _keyword_evidence
    PATH.write_text(new_text, encoding="utf-8")
    print(f"Patched {PATH} (_ev_is_text_like v4)")

if __name__ == "__main__":
    main()
