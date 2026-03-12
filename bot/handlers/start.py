from __future__ import annotations
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()

@router.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Я помогу проверить конспект урока на соответствие ФГОС НОО.\n"
        "Отправь мне документ DOCX или PDF."
    )
