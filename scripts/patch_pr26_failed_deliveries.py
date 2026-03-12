from __future__ import annotations
from pathlib import Path
import re

ROOT = Path(".")
FILES = {
    "api_schemas": ROOT / "api" / "schemas" / "common.py",
    "api_bot_delivery": ROOT / "api" / "routers" / "bot_delivery.py",
    "bot_poll": ROOT / "bot" / "scheduler" / "poll_deliveries.py",
    "worker_process": ROOT / "worker" / "tasks" / "process.py",
    "smoke_test": ROOT / "scripts" / "smoke_test.ps1",
}

def die(msg: str):
    raise SystemExit(msg)

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def write(p: Path, s: str):
    p.write_text(s, encoding="utf-8")

def patch_api_schemas(text: str) -> tuple[str, bool]:
    m = re.search(r'(?ms)^class\s+PendingDeliveryItem\(BaseModel\):\s*\n(?P<body>(?:\s+.+\n)+?)\nclass\s+PendingDeliveriesResponse', text)
    if not m:
        die("Cannot find PendingDeliveryItem block in api/schemas/common.py")

    body = m.group("body")
    if re.search(r'(?m)^\s+status:\s*JobStatus\s*$', body):
        return text, False

    if "chat_id" not in body:
        die("PendingDeliveryItem has no chat_id field; unexpected layout")

    body2 = re.sub(
        r'(?m)^(\s+chat_id:\s*int\s*)$',
        r'\1\n    status: JobStatus\n    error_message: Optional[str] = None',
        body,
        count=1,
    )
    if body2 == body:
        die("Failed to insert status/error_message into PendingDeliveryItem")

    new_text = text[:m.start("body")] + body2 + text[m.end("body"):]
    return new_text, True

def patch_api_bot_delivery(text: str) -> tuple[str, bool]:
    changed = False

    if ".filter(and_(models.Job.status == models.JobStatus.DONE, models.Delivery.delivered_at.is_(None)))" in text:
        text2 = text.replace(
            ".filter(and_(models.Job.status == models.JobStatus.DONE, models.Delivery.delivered_at.is_(None)))",
            ".filter(and_(models.Job.status.in_([models.JobStatus.DONE, models.JobStatus.FAILED]), models.Delivery.delivered_at.is_(None)))",
        )
        if text2 != text:
            text = text2
            changed = True

    def add_fields(inner: str) -> str:
        if "status=" in inner:
            return inner
        return re.sub(
            r'(?m)^(\s*chat_id\s*=\s*[^,]+,\s*)$',
            r'\1\n                    status=job.status.value,\n                    error_message=job.error_message,\n',
            inner,
            count=1,
        )

    def repl(m: re.Match) -> str:
        inner = m.group("inner")
        return "PendingDeliveryItem(\n" + add_fields(inner) + ")"

    text2 = re.sub(
        r'(?ms)PendingDeliveryItem\(\s*\n(?P<inner>.*?\n\s*\)\s*)\)',
        repl,
        text,
    )
    if text2 != text:
        text = text2
        changed = True

    return text, changed

def patch_bot_poll(text: str) -> tuple[str, bool]:
    if 'status = str(item.get("status")' in text:
        return text, False

    pattern = r'(?m)^\s*chat_id\s*=\s*int\(item\[\"chat_id\"\]\)\s*\n\s*job_id\s*=\s*str\(item\[\"job_id\"\]\)\s*$'
    m = re.search(pattern, text)
    if not m:
        die("Cannot find chat_id/job_id assignment block in bot/scheduler/poll_deliveries.py")

    insert = """\
                status = str(item.get(\"status\") or \"DONE\").upper()
                if status == \"FAILED\":
                    err = str(item.get(\"error_message\") or \"\").strip()
                    msg = \"❌ Не удалось обработать документ.\\n\"
                    if err:
                        msg += f\"Причина: {err}\\n\"
                    msg += \"Попробуйте загрузить DOCX или PDF с текстовым слоем.\\n\"
                    msg += f\"job_id: {job_id}\"
                    await bot.send_message(chat_id, msg)
                    await api.ack_delivery(job_id)
                    continue
"""

    text = text[:m.end()] + "\n" + insert + text[m.end():]
    return text, True

def patch_worker_process(text: str) -> tuple[str, bool]:
    if "PDF поврежден или не поддерживается" in text and "has no extractable text" in text:
        return text, False

    start = text.find("# If PDF has no extractable text, mark as needs clarification")
    if start < 0:
        die("Cannot find PDF clarification block in worker/tasks/process.py")

    end = text.find("canonical_path =", start)
    if end < 0:
        die("Cannot find canonical_path after PDF block in worker/tasks/process.py")

    replacement = """\
        # If PDF has parsing error or no extractable text, FAIL fast (no retries).
        if (canonical.get(\"source\") or {}).get(\"format\") == \"pdf\":
            src = canonical.get(\"source\") or {}
            err = src.get(\"error\")
            chars_total = int((canonical.get(\"stats\") or {}).get(\"text_chars_total\") or 0)

            if err:
                msg = f\"PDF поврежден или не поддерживается: {err}\"
                logger.warning(\"process_document: PDF parse error; failing: %s\", msg)
                _update_job(db, job, status=models.JobStatus.FAILED, progress=100, error_message=msg)
                return

            if chars_total == 0:
                msg = \"Не удалось извлечь текст из PDF (похоже на скан). Загрузите DOCX или PDF с текстовым слоем.\"
                logger.warning(\"process_document: PDF has no extractable text; failing: %s\", msg)
                _update_job(db, job, status=models.JobStatus.FAILED, progress=100, error_message=msg, needs_clarification=True)
                return

            logger.info(\"process_document: PDF text detected chars_total=%s; continuing normal pipeline\", chars_total)

"""

    text2 = text[:start] + replacement + text[end:]
    return text2, True

def patch_smoke_test(text: str) -> tuple[str, bool]:
    changed = False
    if "AllowFailed" not in text:
        # Add parameter before -NoAuth
        text2 = re.sub(
            r'(?ms)(\[int\]\s*\$PollSeconds\s*=\s*\d+\s*,\s*\n\s*)(\[switch\]\s*\$NoAuth)',
            r'\1\n  [switch]$AllowFailed,\n\n  \2',
            text,
            count=1,
        )
        if text2 != text:
            text = text2
            changed = True

    # break condition in poll loop
    if 'if ($st -eq "DONE") { break }' in text:
        text = text.replace('if ($st -eq "DONE") { break }', 'if ($st -eq "DONE" -or $st -eq "FAILED") { break }')
        changed = True

    # Replace post-poll DONE-only guard
    if "Job did not reach DONE" in text and "AllowFailed" in text and "Job finished with FAILED" not in text:
        # more robust: use regex around the DONE-only block
        text2 = re.sub(
            r'(?ms)if \(-not \$j -or \$j\.status -ne \"DONE\"\) \{\s*throw \(\"Job did not reach DONE in \{0\}s\" -f \$PollSeconds\)\s*\}\s*\n\s*Print-Issues',
            'if (-not $j -or ($j.status -ne "DONE" -and $j.status -ne "FAILED")) {\n  throw ("Job did not reach DONE/FAILED in {0}s" -f $PollSeconds)\n}\n\nif ($j.status -eq "FAILED") {\n  Write-Host ("Job failed: {0}" -f $j.error_message)\n  Maybe-CheckBotQueue -jobId $jobId -chatId $ChatId\n  Maybe-AckDelivery -jobId $jobId\n  if (-not $AllowFailed) { throw "Job finished with FAILED" }\n  return\n}\n\nPrint-Issues',
            text,
            count=1,
        )
        if text2 != text:
            text = text2
            changed = True

    return text, changed

def main():
    changed_any = False

    p = FILES["api_schemas"]
    if not p.exists():
        die(f"Missing {p}")
    t = read(p)
    t2, ch = patch_api_schemas(t)
    if ch:
        write(p, t2)
        print(f"Patched {p} (PendingDeliveryItem includes status/error_message)")
        changed_any = True
    else:
        print(f"OK {p} (already patched)")

    p = FILES["api_bot_delivery"]
    if not p.exists():
        die(f"Missing {p}")
    t = read(p)
    t2, ch = patch_api_bot_delivery(t)
    if ch:
        write(p, t2)
        print(f"Patched {p} (pending-deliveries includes FAILED + payload fields)")
        changed_any = True
    else:
        print(f"OK {p} (already patched)")

    p = FILES["bot_poll"]
    if not p.exists():
        die(f"Missing {p}")
    t = read(p)
    t2, ch = patch_bot_poll(t)
    if ch:
        write(p, t2)
        print(f"Patched {p} (bot handles FAILED deliveries)")
        changed_any = True
    else:
        print(f"OK {p} (already patched)")

    p = FILES["worker_process"]
    if not p.exists():
        die(f"Missing {p}")
    t = read(p)
    t2, ch = patch_worker_process(t)
    if ch:
        write(p, t2)
        print(f"Patched {p} (fail-fast for bad/scanned PDFs)")
        changed_any = True
    else:
        print(f"OK {p} (already patched)")

    p = FILES["smoke_test"]
    if p.exists():
        t = read(p)
        t2, ch = patch_smoke_test(t)
        if ch:
            write(p, t2)
            print(f"Patched {p} (smoke_test supports FAILED via -AllowFailed)")
            changed_any = True
        else:
            print(f"OK {p} (already patched)")
    else:
        print("Skip scripts/smoke_test.ps1 (not found)")

    if not changed_any:
        print("Nothing changed. PR-26 already applied.")
    else:
        print("PR-26 patches applied.")

if __name__ == "__main__":
    main()
