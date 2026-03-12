from __future__ import annotations

import asyncio
import re
from html import escape as html_escape

from aiogram import Bot
from aiogram.types import BufferedInputFile

from bot.services.api_client import ApiClient


_DOCX_BLOCK_RE = re.compile(r"^p(?P<n>\d{5})$")               # DOCX block: p00005
_PDF_BLOCK_RE = re.compile(r"^p(?P<p>\d{3})b(?P<b>\d{4})$")  # PDF block:  p001b0000


def _format_loc(page: int | None, block_id: str | None) -> str | None:
    """Return a short, human-friendly location (Variant A).

    - DOCX: "абз. N" (derived from block_id like p00005)
    - PDF:  "стр. N" (from page)
    """
    block_id = (block_id or "").strip()

    m = _DOCX_BLOCK_RE.match(block_id)
    if m:
        try:
            n = int(m.group("n"))
            return f"абз. {n}"
        except Exception:
            return "абз."

    if page is not None:
        return f"стр. {page}"

    if _PDF_BLOCK_RE.match(block_id):
        return "стр."

    return block_id or None


def _clean_quote(quote: str, max_len: int = 180) -> str:
    q = (quote or "").strip().replace("\r", " ").replace("\n", " ")
    q = re.sub(r"\s+", " ", q)
    q = html_escape(q)
    if len(q) > max_len:
        q = q[:max_len] + "…"
    return f"«{q}»"


async def poll_deliveries_loop(bot: Bot, api: ApiClient, interval_seconds: int = 10):
    while True:
        try:
            payload = await api.pending_deliveries(limit=20)
            items = payload.get("items", [])

            for item in items:
                chat_id = int(item["chat_id"])
                job_id = str(item["job_id"])

                delivery_summary = item.get("summary") or {}

                # pending-deliveries payload is compact; fetch full job to get issues + needs_clarification
                job = None
                job_summary = {}
                needs_clarification = False
                try:
                    status = (item.get("status") or "").upper()
                    if status == "FAILED":
                        err = item.get("error_message") or "Unknown error"
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ Не удалось обработать документ (job={job_id}).\n{err}",
                        )
                        await api.ack_delivery(job_id)
                        continue
                    job = await api.get_job(job_id, chat_id=chat_id)
                    job_summary = (job or {}).get("summary") or {}
                    needs_clarification = bool((job or {}).get("needs_clarification") or False)
                except Exception:
                    # do not crash delivery loop
                    job = None

                summary = job_summary or delivery_summary

                total = summary.get("total_score")
                max_score = summary.get("max_score")
                top = summary.get("top_issues") or []
                issues = summary.get("issues") or []

                text = "✅ Анализ завершён.\n"
                if total is not None and max_score is not None:
                    text += f"Итог: {total}/{max_score}\n"

                if top:
                    text += "\nОсновные замечания:\n" + "\n".join([f"• {x}" for x in top[:7]])

                evidence_issues = [
                    it for it in issues
                    if isinstance(it, dict)
                    and (
                        (it.get("quote") and str(it.get("quote")).strip())
                        or (it.get("block_id") and str(it.get("block_id")).strip())
                    )
                ]

                # --- Variant A: always show a "Фрагменты" section (either actual quotes or a short fallback) ---
                if evidence_issues:
                    text += f"\n\nФрагменты (первые {min(5, len(evidence_issues))}):\n"
                    for it in evidence_issues[:5]:
                        page = it.get("page")
                        block_id = str(it.get("block_id") or "")
                        quote = str(it.get("quote") or "")

                        loc = _format_loc(page=page, block_id=block_id)
                        loc_html = f"<i>{html_escape(loc)}</i>" if loc else "<i>фрагмент</i>"

                        if quote.strip():
                            text += f"• {loc_html} — {_clean_quote(quote)}\n"
                        else:
                            text += f"• {loc_html}\n"
                else:
                    # No evidence => tell it briefly (and point to highlighted DOCX).
                    if needs_clarification:
                        reason = "похоже, документ без извлекаемого текста (скан/картинки)"
                    else:
                        reason = "по этим замечаниям не удалось выделить цитаты (evidence не найден)"
                    text += f"\n\nФрагменты:\n• {reason}. Смотрите подсветку в DOCX.\n"

                await bot.send_message(chat_id, text)

                # Send artifacts (secure download tied to job_id + chat_id)
                for a in item.get("artifacts", []):
                    artifact_id = str(a["artifact_id"])
                    kind = a.get("kind")
                    filename = a.get("filename", "artifact.bin")

                    content = await api.download_artifact(job_id=job_id, chat_id=chat_id, artifact_id=artifact_id)
                    inp = BufferedInputFile(content, filename=filename)
                    await bot.send_document(chat_id, inp, caption=f"{kind}")

                await api.ack_delivery(job_id)
        except Exception:
            # Keep the bot loop alive no matter what.
            pass

        await asyncio.sleep(interval_seconds)
