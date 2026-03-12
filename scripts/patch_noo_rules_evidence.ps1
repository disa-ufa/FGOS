param(
  [string]$Path = "worker\pipeline\noo_rules.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Path)) {
  throw "File not found: $Path (run from project root)"
}

$text = Get-Content -Path $Path -Raw -Encoding UTF8

# 1) Insert helper _ev_is_text_like after _norm_lc if not present
if ($text -notmatch "def\s+_ev_is_text_like\s*\(") {
  $insert = @'

_EV_CODE_TOKENS_RE = re.compile(
    r"\b(docker|compose|yaml|yml|json|python|alembic|celery|sha256|endpoint|repo|github|fastapi|sqlalchemy|redis|postgres)\b",
    flags=re.IGNORECASE,
)

def _ev_is_text_like(text: str) -> bool:
    # Heuristic filter to prefer natural-language fragments over code/config snippets.
    t = (text or "").strip()
    if not t:
        return False

    # Hard signals for code/config
    if "```" in t:
        return False
    if _EV_CODE_TOKENS_RE.search(t):
        return False
    if re.search(r"[\\/][\w\-\.]+[\\/]", t):  # paths like a/b/c or a\b\c
        return False
    if re.search(r"\b\w+\.\w{1,6}\b", t) and re.search(r"[=:{\[\]}<>]", t):
        return False

    # Ratio of symbol characters (code-y) to total length
    symbols = re.findall(r"[{}\[\]<>;:=|`~$^*]+", t)
    sym_len = sum(len(s) for s in symbols)
    if len(t) >= 40 and (sym_len / max(1, len(t))) > 0.18:
        return False

    # Prefer Cyrillic / sentence-like text
    if not re.search(r"[А-Яа-яЁё]{6,}", t):
        if len(t) > 60:
            return False

    return True

'@

  $pattern = 'def\s+_norm_lc\(s:\s*str\)\s*->\s*str:\s*\r?\n\s*return\s*\(s\s*or\s*""\)\.strip\(\)\.lower\(\)\s*\r?\n'
  $m = [regex]::Match($text, $pattern)
  if (-not $m.Success) {
    throw "Cannot find _norm_lc() to insert helper after."
  }
  $pos = $m.Index + $m.Length
  $text = $text.Substring(0, $pos) + $insert + $text.Substring($pos)
}

# 2) Replace _keyword_evidence with two-pass (text-like first, then fallback)
$newFunc = @'
def _keyword_evidence(
    blocks: List[Dict[str, Any]],
    source_format: str,
    keywords: List[str],
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
'@

$rx = [regex]::new("(?s)def\s+_keyword_evidence\([\s\S]*?\)\s*->\s*List\[Dict\[str,\s*Any\]\]:[\s\S]*?(?=\r?\n\r?\n\r?\ndef\s+evaluate_noo_rubric)", [System.Text.RegularExpressions.RegexOptions]::Multiline)
if (-not $rx.IsMatch($text)) {
  throw "Cannot find _keyword_evidence() block to replace."
}
$text = $rx.Replace($text, $newFunc, 1)

# Ensure Tuple import is present (new function uses Tuple)
if ($text -notmatch "from\s+typing\s+import\s+.*\bTuple\b") {
  $text = $text -replace "(from\s+typing\s+import\s+)([^\r\n]+)", {
    param($m)
    $prefix = $m.Groups[1].Value
    $items = $m.Groups[2].Value
    if ($items -match "\bTuple\b") { return $m.Value }
    return $prefix + $items.TrimEnd() + ", Tuple"
  }, 1
}

Set-Content -Path $Path -Value $text -Encoding UTF8
Write-Host "Patched $Path OK."
