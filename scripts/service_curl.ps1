param(
  [Parameter(Mandatory=$true)][string]$PathQ,
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [ValidateSet('GET','POST','PUT','PATCH','DELETE')][string]$Method = 'GET'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# SERVICE_SECRET can be provided via env or loaded from .env in project root
if (-not $env:SERVICE_SECRET) {
  if (Test-Path .\.env) {
    $line = (Select-String -Path .\.env -Pattern '^SERVICE_SECRET=' -ErrorAction SilentlyContinue).Line
    if ($line) {
      $env:SERVICE_SECRET = $line.Split('=',2)[1]
    }
  }
}

if (-not $env:SERVICE_SECRET) {
  throw "SERVICE_SECRET is not set (set env:SERVICE_SECRET or add SERVICE_SECRET=... to .env)"
}

$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$msg = "$ts.$($Method.ToUpper()).$PathQ"

$hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($env:SERVICE_SECRET))
try {
  $sig = ($hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($msg)) | ForEach-Object { $_.ToString("x2") }) -join ""
} finally {
  $hmac.Dispose()
}

# API expects:
#   X-Service-Timestamp: <unix seconds>
#   X-Service-Signature: HMAC_SHA256(SERVICE_SECRET, "{ts}.{METHOD}.{path?query}")
$cmd = @(
  'curl.exe','-sS',
  '-H',"X-Service-Timestamp: $ts",
  '-H',"X-Service-Signature: $sig",
  "$BaseUrl$PathQ"
)

Write-Host ($cmd -join ' ')
& $cmd[0] $cmd[1..($cmd.Length-1)]
