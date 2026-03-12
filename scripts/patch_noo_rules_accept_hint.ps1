param(
  [string]$Path = "worker\pipeline\noo_rules.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Path)) {
  throw "File not found: $Path (run from project root)"
}

$text = Get-Content -Path $Path -Raw -Encoding UTF8

# Если hint уже есть — выходим
if ($text -match "def\s+_keyword_evidence\([\s\S]*?\bhint\s*:") {
  Write-Host "hint parameter already present in _keyword_evidence(). Nothing to do."
  exit 0
}

# Добавляем hint перед limit (с сохранением отступов)
$pattern = "(\r?\n)(\s*)limit:\s*int\s*=\s*3,"
if ($text -notmatch $pattern) {
  throw "Cannot find 'limit: int = 3,' in _keyword_evidence() signature. Open $Path and check formatting."
}

$text = [regex]::Replace(
  $text,
  $pattern,
  "`$1`$2hint: str | None = None,`$1`$2limit: int = 3,",
  1
)

Set-Content -Path $Path -Value $text -Encoding UTF8
Write-Host "Patched ${Path}: added hint parameter to _keyword_evidence()."
