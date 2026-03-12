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

# 2) Patch worker logging filter to read request_id from contextvar
if (-not (Test-Path $LogPath)) { throw "File not found: $LogPath" }
$logText = Get-Content -Path $LogPath -Raw -Encoding UTF8

if ($logText -notmatch "from worker\.observability\.request_id import get_request_id") {
  $logText = $logText -replace "import os", "import os`r`n`r`nfrom worker.observability.request_id import get_request_id"
}

# Replace filter() body (safe, single occurrence)
$logText = [regex]::Replace(
  $logText,
  "def filter\(self, record: logging\.LogRecord\) -> bool:\s*[\s\S]*?return True",
  "def filter(self, record: logging.LogRecord) -> bool:`r`n        # Inject request_id field so formatters can include it.`r`n        try:`r`n            record.request_id = get_request_id()`r`n        except Exception:`r`n            record.request_id = \"-\"`r`n        return True",
  1
)

Set-Content -Path $LogPath -Value $logText -Encoding UTF8
Write-Host "Patched $LogPath (request_id from contextvar)"

# 3) Patch worker task to set request_id = job_uuid and clear in finally
if (-not (Test-Path $ProcessPath)) { throw "File not found: $ProcessPath" }
$p = Get-Content -Path $ProcessPath -Raw -Encoding UTF8

if ($p -notmatch "worker\.observability\.request_id import set_request_id") {
  # Insert import near other worker.observability imports
  $p = $p -replace "(from worker\.observability\.logging import setup_logging as setup_worker_logging\r?\n)",
                   "`$1from worker.observability.request_id import set_request_id`r`n"
}

# After job_uuid is computed, set request_id
if ($p -notmatch "set_request_id\(str\(job_uuid\)\)") {
  $p = $p -replace "(job_uuid\s*=\s*uuid\.UUID\([^\r\n]+\)\r?\n)",
                   "`$1        set_request_id(str(job_uuid))`r`n"
}

# In finally: clear request id before closing db
if ($p -match "finally:\s*\r?\n\s*db\.close\(\)") {
  $p = $p -replace "(finally:\s*\r?\n)(\s*)db\.close\(\)",
                   "`$1`$2set_request_id(\"-\")`r`n`$2db.close()"
}

Set-Content -Path $ProcessPath -Value $p -Encoding UTF8
Write-Host "Patched $ProcessPath (set_request_id per job)"
