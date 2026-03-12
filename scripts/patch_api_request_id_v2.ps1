param(
  [string]$Path = "api\main.py"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Path)) { throw "File not found: $Path" }

$text = Get-Content -Path $Path -Raw -Encoding UTF8

# 1) Ensure imports
if ($text -notmatch "from api\.observability\.logging import setup_logging") {
  $text = $text -replace "from fastapi import FastAPI\r?\nfrom fastapi\.responses import JSONResponse\r?\n",
    "from fastapi import FastAPI`r`nfrom fastapi.responses import JSONResponse`r`nfrom starlette.requests import Request`r`nfrom starlette.responses import Response`r`n`r`nfrom api.observability.logging import setup_logging`r`nfrom api.observability.request_id import sanitize_request_id, generate_request_id, set_request_id, reset_request_id`r`n"
}

# 2) Ensure setup_logging() called once (place before UTF8JSONResponse class)
if ($text -notmatch "setup_logging\(\)") {
  $text = $text -replace "class UTF8JSONResponse", "setup_logging()`r`n`r`nclass UTF8JSONResponse"
}

# 3) Add request-id middleware
if ($text -notmatch "request_id_middleware") {
  $middleware = @'
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID")
    rid = sanitize_request_id(incoming) or generate_request_id()
    token = set_request_id(rid)
    try:
        response: Response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = rid
    return response
'@

  $text = [regex]::Replace($text, "(app = FastAPI\([\s\S]*?\)\r?\n)", "`$1`r`n$middleware`r`n", 1)
}

Set-Content -Path $Path -Value $text -Encoding UTF8
Write-Host "Patched ${Path}: request-id middleware + logging enabled."
