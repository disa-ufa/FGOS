# FGOS Helper (v0.2) — Telegram bot + API + Worker (ФГОС НОО)

Variant B (Telegram bot + API + Worker):
- Telegram bot (aiogram 3) принимает DOCX/PDF
- API (FastAPI) сохраняет файл, создаёт job и ставит задачу в очередь
- Worker (Celery) выполняет пайплайн **Parse → Extract → Check → Artifacts**
- Bot опрашивает API (pending deliveries) и отправляет пользователю результат

Выходные артефакты (MVP):
- `canonical_noo.json`
- `extracted_noo.json`
- `Отчет_ФГОС_НОО.pdf`

## Быстрый старт

1) Скопируйте `.env.example` → `.env` и заполните `BOT_TOKEN`.
2) Запустите:
```bash
docker compose up --build
```

3) Откройте бота в Telegram, отправьте DOCX/PDF.
4) Через некоторое время придёт отчёт `Отчет_ФГОС_НОО.pdf` + доп. артефакты (JSON).

## Что дальше (P0)
- Улучшить отчёт (кириллица/таблица критериев/доказательства)
- Добавить артефакт **HIGHLIGHTED_DOCX** (подсветка проблемных мест в исходном конспекте) — обязательный пункт ТЗ
- Улучшить evidence-привязки (страницы/абзацы), стабильность канонизации
- Hardening: убрать `create_all` (только alembic), усилить object-level security на скачивание


## Примечание по зависимостям
- aiogram 3.6.0 совместим с aiohttp 3.9.x (в MVP зафиксировано aiohttp==3.9.5).

- Для bot: aiogram 3.6.0 требует pydantic < 2.8, поэтому зафиксировано pydantic==2.7.4.


## Документация
- `docs/ТЗ_FGOS_Helper_ФГОС_НОО_Telegram_v0.2.docx`
- `docs/Структура_проекта_FGOS_Helper_компоненты_v0.2.docx`


## Примечание (v0.2.2)
- Исправлен порядок вставки в БД при загрузке документа (flush doc/job перед созданием Delivery), чтобы избежать ForeignKeyViolation.

## Smoke-test (локально)
Для быстрой проверки пайплайна без Telegram можно прогнать smoke-тест (Windows PowerShell).
Требуется `SERVICE_SECRET` (из `.env`).

```powershell
# (по желанию) подхватить SERVICE_SECRET из .env
$env:SERVICE_SECRET = (Select-String -Path .\.env -Pattern '^SERVICE_SECRET=').Line.Split('=',2)[1]

powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 `
  -FilePath .\evidence_test.pdf `
  -ChatId 7301465713 `
  -BaseUrl "http://127.0.0.1:8000" `
  -DownloadArtifacts -OutDir out `
  -CheckBotQueue -AckDelivery
```

Примечание: эндпоинт `/v1/artifacts/{artifact_id}/download` **deprecated** (410). Для скачивания используйте
`/v1/bot/jobs/{job_id}/artifacts/{artifact_id}/download?chat_id=...` (smoke-test это уже учитывает).

## API подсказка
Добавлен helper-эндпоинт для отладки/инспекции результата по одной задаче:

```
GET /v1/bot/jobs/{job_id}?chat_id=...   (service-auth)
```

## Observability

### API metrics
Prometheus-метрики API доступны по адресу:

```text
http://127.0.0.1:18000/metrics

## Known limitations

### Non-root worker on Windows bind mounts
A non-root worker mode was explored, but it is **not** considered a supported local setup on Windows.

When Docker uses a Windows bind mount such as:

```yaml
volumes:
  - ./data:/data

  ## Project status

### Closed
- Secret handling stabilized (`.env` is not tracked, `.env.example` is used as template)
- CI is configured
- Secret scan is configured
- Required `HIGHLIGHTED_DOCX` artifact is generated for DOCX inputs
- Upload → queue → processing → artifact download flow is working
- Object-level auth checks with `chat_id` are covered by tests
- Worker timestamps were migrated to timezone-aware UTC
- API metrics endpoint is working
- Worker metrics endpoint is working in Celery `prefork` mode
- Local Windows smoke test flow is stable

### Partial
- Non-root worker mode was investigated
- Production-style override was explored
- The limitation is understood, but the solution is not yet considered production-ready for Windows bind mounts

### Remaining
- Revisit non-root worker in a Linux-safe storage/volume setup
- Verify the same flow on Linux/VPS deployment
- Optionally add a compact architecture diagram / component overview
- Optionally add a release checklist for future changes

## Release checklist

Before pushing changes, verify the following:

### Code and tests
- Run local tests:
  ```powershell
  python -m pytest -q