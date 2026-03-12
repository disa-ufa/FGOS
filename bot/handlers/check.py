from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

import aiohttp

from bot.services.api_client import ApiClient, ApiRequestError
from bot.config import settings

router = Router()

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.message(F.document)
async def handle_document(message: Message):
    doc = message.document
    if not doc:
        return

    if doc.mime_type not in ALLOWED_MIME:
        await message.answer("Поддерживаются только DOCX и PDF.")
        return

    # P0: Telegram может не дать скачать большой файл (getFile/download).
    if doc.file_size and doc.file_size > settings.tg_max_file_bytes:
        mb = doc.file_size / (1024 * 1024)
        await message.answer(
            f"Файл слишком большой для обработки через Telegram-бота.\n"
            f"Размер: {mb:.1f} МБ.\n"
            f"Максимум для бота сейчас: {settings.tg_max_file_mb} МБ.\n\n"
            f"Сожмите файл, уменьшите размер или разделите на части."
        )
        return

    await message.answer("Файл принят. Идёт анализ…")

    # download file from telegram
    bot = message.bot
    try:
        file = await bot.get_file(doc.file_id)
        stream = await bot.download_file(file.file_path)
        content = stream.read()
    except TelegramBadRequest as e:
        if "file is too big" in str(e).lower():
            await message.answer(
                f"Telegram не позволяет боту скачать этот файл (слишком большой).\n"
                f"Попробуйте файл до {settings.tg_max_file_mb} МБ."
            )
            return
        await message.answer(f"Ошибка Telegram при получении файла: {e}")
        return
    except Exception as e:
        await message.answer(f"Не удалось скачать файл из Telegram: {e}")
        return

    api = ApiClient(settings.api_url, settings.service_secret)
    try:
        resp = await api.upload_document(
            telegram_user_id=message.from_user.id if message.from_user else 0,
            chat_id=message.chat.id,
            filename=doc.file_name or "document",
            content_type=doc.mime_type or "application/octet-stream",
            data=content,
        )
    except ApiRequestError as e:
        # Это как раз наш PR-02: signature/size limit и т.п.
        await message.answer(f"Файл отклонён сервисом: {e.detail}")
        return
    except aiohttp.ClientError as e:
        await message.answer(f"Не удалось связаться с API: {e}")
        return

    await message.answer(f"Задача поставлена в очередь. job_id: {resp.get('job_id')}")