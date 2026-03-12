from __future__ import annotations

import asyncio
import random

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from bot.config import settings
from bot.handlers.start import router as start_router
from bot.handlers.check import router as check_router
from bot.services.api_client import ApiClient
from bot.scheduler.poll_deliveries import poll_deliveries_loop


async def _run_polling_once() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(start_router)
    dp.include_router(check_router)

    api = ApiClient(settings.api_url, settings.service_secret)
    deliveries_task = asyncio.create_task(poll_deliveries_loop(bot, api, interval_seconds=10))

    try:
        await dp.start_polling(bot)
    finally:
        deliveries_task.cancel()
        try:
            await deliveries_task
        except Exception:
            pass
        # Close aiohttp session used by aiogram
        try:
            await bot.session.close()
        except Exception:
            pass


async def main() -> None:
    # In some environments (corporate DNS/VPN, flaky networks), resolving api.telegram.org
    # can fail temporarily. If we crash-loop, Docker restarts the container too fast.
    # Instead, retry polling with backoff.
    delay = 1.0
    while True:
        try:
            await _run_polling_once()
            # Normal shutdown of polling (SIGTERM) -> exit
            return
        except TelegramNetworkError as e:
            jitter = random.uniform(0.0, 0.5)
            wait = min(60.0, delay) + jitter
            print(f"Telegram network error: {e}. Retry in {wait:.1f}s")
            await asyncio.sleep(wait)
            delay = min(60.0, delay * 1.7)
        except Exception:
            # Unexpected error: surface it (so we don't hide bugs)
            raise


if __name__ == "__main__":
    asyncio.run(main())
