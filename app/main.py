from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import get_settings
from app.logging_config import configure_logging
from app.bot.handlers import register_handlers

logger = logging.getLogger(__name__)


def create_dispatcher() -> Dispatcher:
    """Create an empty dispatcher and wire placeholder handlers."""
    dispatcher = Dispatcher()
    register_handlers(dispatcher)
    return dispatcher


def create_bot(token: str) -> Bot:
    """Create a bot client from token."""
    return Bot(token=token)


async def run_bot() -> None:
    """Run minimal bot runtime scaffold."""
    settings = get_settings()
    settings.require_production_secrets()
    configure_logging(settings.log_level)

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN must be set for runtime execution")

    bot = create_bot(settings.bot_token.get_secret_value())
    dp = create_dispatcher()

    try:
        if settings.webhook_mode_enabled and settings.app_env != "development":
            logger.info("Starting webhook mode with path=%s", settings.telegram_webhook_path)
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(url=f"{settings.telegram_webhook_url}{settings.telegram_webhook_path}")
            await dp.start_webhook(
                webhook_path=settings.telegram_webhook_path,
                skip_updates=True,
                on_startup=None,
                on_shutdown=None,
                bot=bot,
                request_timeout=settings.bot_max_request_timeout,
            )
        else:
            logger.info("Starting polling mode")
            await dp.start_polling(bot, request_timeout=settings.bot_max_request_timeout)
    finally:
        await bot.session.close()


async def main() -> None:
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())

