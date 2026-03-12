<# 
FGOS smoke test (PR-16.1)

РџСЂРѕРІРµСЂСЏРµС‚ API РїР°Р№РїР»Р°Р№РЅ:
1) Upload РґРѕРєСѓРјРµРЅС‚Р° -> РїРѕР»СѓС‡Р°РµС‚ job_id/doc_id
2) Poll /v1/jobs/{job_id} РґРѕ DONE
3) РџРµС‡Р°С‚Р°РµС‚ issues РіРґРµ РЅР°Р№РґРµРЅ block_id/quote
РћРїС†РёРѕРЅР°Р»СЊРЅРѕ:
-CheckBotQueue      : СЃРјРѕС‚СЂРёС‚ /v1/bot/pending-deliveries
-AckDelivery        : POST /v1/bot/deliveries/{job_id}/ack
-DownloadArtifacts  : СЃРєР°С‡РёРІР°РµС‚ Р°СЂС‚РµС„Р°РєС‚С‹ job РІ -OutDir (С‡РµСЂРµР· /v1/bot/jobs/{job_id}?chat_id=... Рё /download)

РўСЂРµР±СѓРµС‚СЃСЏ SERVICE_SECRET (РёР· env РёР»Рё .env) РґР»СЏ РїРѕРґРїРёСЃР°РЅРЅС‹С… СЌРЅРґРїРѕРёРЅС‚РѕРІ.
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$FilePath,

  [Parameter(Mandatory=$true)]
  [long]$ChatId,

  [string]$BaseUrl = "http://127.0.0.1:8000",

  # РњРѕР¶РЅРѕ РїРµСЂРµРґР°С‚СЊ СЃРµРєСЂРµС‚ РЅР°РїСЂСЏРјСѓСЋ (СѓРґРѕР±РЅРѕ РІ CI). РРЅР°С‡Рµ Р±СѓРґРµС‚ РІР·СЏС‚ РёР· env/.env
  [string]$ServiceSecret,

  [int]$PollSeconds = 25,

  [switch]$AllowFailed,
  [switch]$NoAuth,

  [switch]$CheckBotQueue,
  [int]$PendingLimit = 20,

  [switch]$AckDelivery,

  [switch]$DownloadArtifacts,
  [string]$OutDir = "out"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Make console UTF-8 friendly (best-effort) ---
try { chcp 65001 *> $null } catch {}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Get-ProjectRoot {
  # scripts\smoke_test.ps1 -> project root is parent of scripts
  try {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  } catch {
    return (Get-Location).Path
  }
}

function Resolve-InputPath([string]$p) {
  if ([IO.Path]::IsPathRooted($p)) { return (Resolve-Path $p).Path }
  $root = Get-ProjectRoot
  $candidate = Join-Path $root $p
  if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
  return (Resolve-Path (Join-Path (Get-Location).Path $p)).Path
}

function Load-DotEnvIfPresent {
  $root = Get-ProjectRoot
  $envPath = Join-Path $root ".env"
  if (-not (Test-Path $envPath)) { return }

  $lines = Get-Content -Path $envPath -ErrorAction SilentlyContinue
  foreach ($line in $lines) {
    $t = ($line -as [string]).Trim()
    if (-not $t) { continue }
    if ($t.StartsWith("#")) { continue }
    if ($t -notmatch "^\s*([^#=\s]+)\s*=\s*(.*)\s*$") { continue }

    $k = $Matches[1].Trim()
    $k = $k.TrimStart([char]0xFEFF)
    $v = $Matches[2].Trim()

    # remove quotes if present (safe; no escaping headaches)
    if ($v.Length -ge 2) {
      $first = $v[0]
      $last  = $v[$v.Length - 1]
      if ((($first -eq '"') -and ($last -eq '"')) -or (($first -eq "'") -and ($last -eq "'"))) {
        $v = $v.Substring(1, $v.Length - 2)
      }
    }

    # don't override existing env
    $existing = [Environment]::GetEnvironmentVariable($k, "Process")
    if (-not [string]::IsNullOrWhiteSpace($existing)) { continue }

    [Environment]::SetEnvironmentVariable($k, $v, "Process")
  }
}

function New-HmacSigHex([string]$secret, [string]$message) {
  $hmac = [System.Security.Cryptography.HMACSHA256]::new([System.Text.Encoding]::UTF8.GetBytes($secret))
  try {
    $hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($message))
    return ($hash | ForEach-Object { $_.ToString("x2") }) -join ""
  } finally {
    $hmac.Dispose()
  }
}

function Build-ServiceHeaders([string]$method, [string]$pathWithQuery, [string]$secret) {
  $ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $msg = "$ts.$method.$pathWithQuery"
  $sig = New-HmacSigHex -secret $secret -message $msg
  return @{
    "X-Service-Timestamp" = "$ts"
    "X-Service-Signature" = "$sig"
  }
}

function Ensure-Secret {
  if ($NoAuth) { return $null }

  if ($ServiceSecret) {
    return $ServiceSecret
  }

  # try env/.env
  Load-DotEnvIfPresent
  if (-not [string]::IsNullOrWhiteSpace($env:SERVICE_SECRET)) { return $env:SERVICE_SECRET }

  throw "SERVICE_SECRET is not set (param/env/.env). Example: `$env:SERVICE_SECRET = '...' (from .env)"
}

function Invoke-ServiceGet([string]$path) {
  $secret = Ensure-Secret
  $headers = @{}
  if (-not $NoAuth) {
    $headers = Build-ServiceHeaders -method "GET" -pathWithQuery $path -secret $secret
  }
  return Invoke-RestMethod -Uri ($BaseUrl + $path) -Headers $headers
}

function Invoke-ServicePost([string]$path) {
  $secret = Ensure-Secret
  $headers = @{}
  if (-not $NoAuth) {
    $headers = Build-ServiceHeaders -method "POST" -pathWithQuery $path -secret $secret
  }
  return Invoke-RestMethod -Method Post -Uri ($BaseUrl + $path) -Headers $headers
}

function Get-CurlNullConfigPath {
  # Р”Р»СЏ curl.exe РЅР° Windows: "NUL". (Р•СЃР»Рё РІРґСЂСѓРі Р·Р°РїСѓСЃС‚СЏС‚ РїРѕРґ Linux вЂ” Р±СѓРґРµС‚ /dev/null)
  if ($env:OS -eq "Windows_NT") { return "NUL" }
  return "/dev/null"
}

function Get-CurlCommonArgs {
  # Р’Р°Р¶РЅРѕ: СѓР±РёСЂР°РµРј РІР»РёСЏРЅРёРµ РїСЂРѕРєСЃРё/.curlrc, РґРѕР±Р°РІР»СЏРµРј СЂРµС‚СЂР°Рё
  $nullCfg = Get-CurlNullConfigPath
  return @(
    "--config", $nullCfg,
    "--noproxy", "*",
    "--retry", "3",
    "--retry-all-errors",
    "--retry-delay", "1",
    "--connect-timeout", "10",
    "--max-time", "180",
    "--fail-with-body",
    "-sS"
  )
}

function Curl-UploadDocument([string]$fileAbsPath, [long]$chatId) {
  $path = "/v1/documents"
  $headers = @()

  if ($NoAuth) {
    Write-Warning "NoAuth specified: uploading without service auth headers (may fail if API requires it)."
  } else {
    $secret = Ensure-Secret
    $h = Build-ServiceHeaders -method "POST" -pathWithQuery $path -secret $secret
    foreach ($k in $h.Keys) {
      $headers += @("-H", ("{0}: {1}" -f $k, $h[$k]))
    }
  }

  # mime type by extension
  $mime = "application/octet-stream"
  $ext = [IO.Path]::GetExtension($fileAbsPath).ToLowerInvariant()
  if ($ext -eq ".pdf") { $mime = "application/pdf" }
  elseif ($ext -eq ".docx") { $mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }
  elseif ($ext -eq ".doc") { $mime = "application/msword" }

  Write-Host ("Uploading: {0} ({1} bytes, mime={2})" -f (Split-Path $fileAbsPath -Leaf), (Get-Item $fileAbsPath).Length, $mime)

  $tmp = [IO.Path]::GetTempFileName()
  try {
    $curlArgs = @(Get-CurlCommonArgs) + @(
      "-H","Expect:",
      "-o", $tmp
    ) + $headers + @(
      "-F","telegram_user_id=1",
      "-F",("chat_id={0}" -f $chatId),
      "-F",("file=@{0};type={1}" -f $fileAbsPath, $mime),
      ($BaseUrl + $path)
    )

    $curlOut = & curl.exe @curlArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      $body = ""
      try { $body = [IO.File]::ReadAllText($tmp, [System.Text.Encoding]::UTF8) } catch {}
      throw ("curl upload failed (exit={0}). curl_out={1}. Body: {2}" -f $LASTEXITCODE, ($curlOut -join "`n"), $body)
    }

    $rawText = ([IO.File]::ReadAllText($tmp, [System.Text.Encoding]::UTF8)).Trim()
    if (-not $rawText.StartsWith("{")) {
      throw ("Upload failed, non-JSON response: {0}" -f $rawText)
    }

    try {
      return $rawText | ConvertFrom-Json
    } catch {
      throw ("Upload failed, invalid JSON: {0}" -f $rawText)
    }
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Print-Issues($issues, [int]$limit = 5) {
  if (-not $issues) { 
    Write-Host "No issues in response."
    return 
  }

  $list = @($issues | Where-Object { $_ -and ($_.block_id -or $_.quote) } | Select-Object -First $limit)
  if ($list.Count -eq 0) {
    Write-Host "No evidence issues with block_id/quote found."
    return
  }

  Write-Host ("Evidence issues (first {0}):" -f $list.Count)
  foreach ($it in $list) {
    $page = $it.page
    $block = $it.block_id
    Write-Host ("- {0} (score={1}, page={2}, block={3})" -f $it.title, $it.score, $page, $block)
    if ($it.quote) {
      Write-Host ("    {0}" -f $it.quote)
    }
  }
}

function Maybe-CheckBotQueue([string]$jobId, [long]$chatId) {
  if (-not $CheckBotQueue) { return }

  if ($NoAuth) {
    Write-Warning "CheckBotQueue requires service auth headers. Skipping (NoAuth enabled)."
    return
  }

  $path = "/v1/bot/pending-deliveries?limit=$PendingLimit"
  $r = Invoke-ServiceGet -path $path

  $items = @($r.items)
  Write-Host ("Pending deliveries: {0}" -f $items.Count)

  $hit = $items | Where-Object { $_.job_id -eq $jobId -and [long]$_.chat_id -eq $chatId } | Select-Object -First 1
  if ($hit) {
    Write-Host ("Found delivery for this job: job_id={0} chat_id={1} doc_id={2}" -f $hit.job_id, $hit.chat_id, $hit.doc_id)
  } else {
    Write-Host "No pending delivery found for this job/chat_id."
  }
}

function Maybe-AckDelivery([string]$jobId) {
  if (-not $AckDelivery) { return }

  if ($NoAuth) {
    Write-Warning "AckDelivery requires service auth headers. Skipping (NoAuth enabled)."
    return
  }

  $path = "/v1/bot/deliveries/$jobId/ack"
  $resp = Invoke-ServicePost -path $path
  Write-Host ("Ack delivery: {0}" -f ($resp.ok))
}

function Maybe-DownloadArtifacts([string]$jobId, [long]$chatId) {
  if (-not $DownloadArtifacts) { return }

  if ($NoAuth) {
    Write-Warning "DownloadArtifacts requires service auth headers. Skipping (NoAuth enabled)."
    return
  }

  $outAbs = $OutDir
  if (-not [IO.Path]::IsPathRooted($outAbs)) {
    $outAbs = Join-Path (Get-Location).Path $OutDir
  }
  New-Item -ItemType Directory -Force -Path $outAbs | Out-Null

  # Get artifacts list from bot job endpoint (chat-scoped)
  $jobPath = "/v1/bot/jobs/${jobId}?chat_id=$chatId"
  $r = Invoke-ServiceGet -path $jobPath

  $arts = @($r.artifacts)
  Write-Host ("Artifacts: {0}" -f $arts.Count)

  foreach ($a in $arts) {
    $aid = [string]$a.artifact_id
    $fname = [string]$a.filename
    if (-not $fname) { $fname = "$aid.bin" }

    # sanitize filename (windows)
    $safe = ($fname -replace '[<>:"/\\|?*]', '_')
    $dest = Join-Path $outAbs $safe

    $dlPath = "/v1/bot/jobs/${jobId}/artifacts/$aid/download?chat_id=$chatId"

    $headers = @()
    $secret = Ensure-Secret
    $h = Build-ServiceHeaders -method "GET" -pathWithQuery $dlPath -secret $secret
    foreach ($k in $h.Keys) { $headers += @("-H", ("{0}: {1}" -f $k, $h[$k])) }

    $curlArgs = @(Get-CurlCommonArgs) + @(
      "-L",
      "-o", $dest
    ) + $headers + @(
      ($BaseUrl + $dlPath)
    )

    $curlOut = & curl.exe @curlArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
      throw ("curl download failed (exit={0}) for {1}. curl_out={2}" -f $LASTEXITCODE, $dlPath, ($curlOut -join "`n"))
    }

    Write-Host ("Downloaded: {0}" -f $dest)
  }
}

# ---------------- MAIN ----------------
Write-Host "FGOS smoke_test PR-16.1"

$fileAbs = Resolve-InputPath $FilePath
$upload = Curl-UploadDocument -fileAbsPath $fileAbs -chatId $ChatId

if (-not $upload.job_id) {
  throw ("Upload succeeded but job_id missing. Raw response: {0}" -f ($upload | ConvertTo-Json -Depth 8))
}

$jobId = [string]$upload.job_id
$docId = [string]$upload.doc_id

Write-Host ("JOB={0} doc_id={1} status={2}" -f $jobId, $docId, $upload.status)

# poll job
$j = $null
for ($i=0; $i -lt $PollSeconds; $i++) {
  $j = Invoke-ServiceGet -path ("/v1/jobs/${jobId}?chat_id=$ChatId")
  $st = [string]$j.status
  Write-Host ("Job status: {0}" -f $st)
  if ($st -eq "DONE" -or $st -eq "FAILED") { break }
  Start-Sleep 1
}

if (-not $j) {
  throw ("Job did not return a status")
}

if ($j.status -eq "FAILED") {
  Write-Host "Job status: FAILED"
  if ($j.error_message) { Write-Host ("Error: {0}" -f $j.error_message) }
  if (-not $AllowFailed) {
    throw ("Job failed: {0}" -f $j.error_message)
  }
} elseif ($j.status -ne "DONE") {
  throw ("Unexpected job status: {0}" -f $j.status)
}

if ($j.status -eq "DONE") { Print-Issues -issues $j.summary.issues -limit 5 }

Maybe-DownloadArtifacts -jobId $jobId -chatId $ChatId
Maybe-CheckBotQueue -jobId $jobId -chatId $ChatId
Maybe-AckDelivery -jobId $jobId
