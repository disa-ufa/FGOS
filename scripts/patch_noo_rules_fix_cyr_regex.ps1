param(
  [string]$Path = "worker\pipeline\noo_rules.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Path)) {
  throw "File not found: $Path (run from project root)"
}

$text = Get-Content -Path $Path -Raw -Encoding UTF8

# Меняем только строку вида:
# if not re.search(r"[...]{6,}", t):
# на безопасный диапазон Unicode (ASCII в исходнике)
$text2 = [regex]::Replace(
  $text,
  'if not re\.search\(r"\[[^"]+\]\{6,\}", t\):',
  'if not re.search(r"[\\u0400-\\u04FF]{6,}", t):',
  1
)

if ($text2 -eq $text) {
  Write-Host "No matching Cyrillic regex line found (maybe already fixed)."
} else {
  Set-Content -Path $Path -Value $text2 -Encoding UTF8
  Write-Host "Patched ${Path}: fixed Cyrillic regex to \\u0400-\\u04FF."
}
