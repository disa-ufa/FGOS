# Smoke test

Скрипт: `scripts/smoke_test.ps1` (PR-15.3)

## Быстрый запуск (Windows PowerShell / PowerShell)

Из корня проекта (`C:\fgos`):

```powershell
# (опционально) чтобы кириллица печаталась нормально
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Вариант A: секрет берётся из .env автоматически (нужна строка SERVICE_SECRET=...)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 `
  -FilePath .\evidence_test.pdf `
  -ChatId 7301465713 `
  -BaseUrl "http://127.0.0.1:8000"

# Вариант B: передать секрет явно
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 `
  -FilePath .\evidence_test.pdf `
  -ChatId 7301465713 `
  -BaseUrl "http://127.0.0.1:8000" `
  -ServiceSecret "<SERVICE_SECRET из .env>"
```

## Доп. опции

- `-DownloadArtifacts -OutDir out` — скачает артефакты (pdf-отчёт + extracted/canonical json)
- `-CheckBotQueue` — покажет `pending-deliveries` (limit=5)
- `-AckDelivery` — сделает `ack` на delivery для текущего `job_id`

Пример полного запуска:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 `
  -FilePath .\evidence_test.pdf `
  -ChatId 7301465713 `
  -BaseUrl "http://127.0.0.1:8000" `
  -DownloadArtifacts -OutDir out `
  -CheckBotQueue -AckDelivery
```

> Важно: `BaseUrl` лучше указывать как `http://127.0.0.1:8000` (а не `localhost`),
> чтобы не упереться в IPv6/WinHTTP нюансы.
