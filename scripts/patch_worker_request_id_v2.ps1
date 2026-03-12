param(
  [string]$ProcessPath = "worker\tasks\process.py",
  [string]$LogPath = "worker\observability\logging.py",
  [string]$ReqIdPath = "worker\observability\request_id.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 1) Ensure request_id module exists
if (-not (Test-Path $ReqIdPath)) {
@'
from __future__ import annotations

import contextvars
import re
import uuid
from typing import Optional

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_ALLOWED = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

def sanitize_request_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if _ALLOWED.match(v):
        return v
    return None

def generate_request_id() -> str:
    return uuid.uuid4().hex

def set_request_id(request_id: str):
    return request_id_var.set(request_id)

def reset_request_id(token) -> None:
    request_id_var.reset(token)

def get_request_id() -> str:
    return request_id_var.get()
'@ | Set-Content -Encoding UTF8 $ReqIdPath
  Write-Host "Created $ReqIdPath"
}

# 2) Patch worker logging to read request_id from contextvar
if (-not (Test-Path $LogPath)) { throw "File not found: $LogPath" }
$logText = Get-Content -Path $LogPath -Raw -Encoding UTF8

if ($logText -notmatch "from worker\.observability\.request_id import get_request_id") {
  $logText = $logText -replace "import os\r?\n", "import os`r`n`r`nfrom worker.observability.request_id import get_request_id`r`n"
}

$replacement = @'
class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = get_request_id()
        except Exception:
            record.request_id = "-"
        return True
'@

$logText = [regex]::Replace(
  $logText,
  "(?s)class RequestIdFilter\(logging\.Filter\):\s*def filter\(self, record: logging\.LogRecord\) -> bool:\s*.*?return True",
  $replacement,
  1
)

Set-Content -Path $LogPath -Value $logText -Encoding UTF8
Write-Host "Patched $LogPath (request_id from contextvar)"

# 3) Patch worker task to set request_id = job_uuid and reset in finally
if (-not (Test-Path $ProcessPath)) { throw "File not found: $ProcessPath" }
$lines = Get-Content -Path $ProcessPath -Encoding UTF8
$new = New-Object System.Collections.Generic.List[string]

$importAdded = $false
$dbTokenAdded = $false
$tokenSetAdded = $false
$resetAdded = $false

for ($i=0; $i -lt $lines.Count; $i++) {
  $line = $lines[$i]
  $new.Add($line)

  if (-not $importAdded -and $line -match "^from worker\.observability\.logging import setup_logging as setup_worker_logging") {
    $new.Add("from worker.observability.request_id import set_request_id, reset_request_id")
    $importAdded = $true
  }

  if (-not $dbTokenAdded -and $line -match "^\s*db = SessionLocal\(\)\s*$") {
    $indent = ($line -replace "db = SessionLocal\(\)\s*$","")
    $new.Add("${indent}rid_token = None")
    $dbTokenAdded = $true
  }

  if (-not $tokenSetAdded -and $line -match "^\s*job_uuid\s*=\s*uuid\.UUID\(") {
    $indent = ($line -replace "job_uuid\s*=\s*uuid\.UUID\([\s\S]*$","")
    $new.Add("${indent}rid_token = set_request_id(str(job_uuid))")
    $tokenSetAdded = $true
  }

  if (-not $resetAdded -and $line -match "^\s*db\.close\(\)\s*$") {
    # Insert reset right before db.close(), in the same indent level.
    $indent = ($line -replace "db\.close\(\)\s*$","")
    # Remove the db.close we just added; re-add with reset block first.
    $new.RemoveAt($new.Count - 1)

    $new.Add("${indent}if rid_token is not None:")
    $new.Add("${indent}    reset_request_id(rid_token)")
    $new.Add($line)
    $resetAdded = $true
  }
}

Set-Content -Path $ProcessPath -Value $new -Encoding UTF8
Write-Host "Patched $ProcessPath (set/reset request_id per job)"
