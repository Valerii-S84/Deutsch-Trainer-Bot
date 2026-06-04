from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.config import get_settings
from app.logging_config import configure_logging
from app.bot.dispatcher import build_dispatcher

logger = logging.getLogger(__name__)


def create_dispatcher() -> Dispatcher:
    """Create and configure a dispatcher with all production-relevant routers."""
    return build_dispatcher()


def create_bot(token: str) -> Bot:
    """Create a bot client from token."""
    return Bot(token=token)


async def health_check(_request: web.Request) -> web.Response:
    """Return a minimal container health response."""
    return web.json_response({"status": "ok"})


def create_webhook_app(
    dispatcher: Dispatcher,
    bot: Bot,
    *,
    webhook_path: str,
    webhook_secret: str,
) -> web.Application:
    """Create an aiohttp app that forwards Telegram webhook updates to aiogram."""
    app = web.Application()
    app.router.add_get("/health", health_check)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=webhook_secret,
    ).register(app, path=webhook_path)
    setup_application(app, dispatcher, bot=bot)
    return app


async def run_webhook(
    bot: Bot,
    dispatcher: Dispatcher,
    *,
    webhook_url: str,
    webhook_path: str,
    webhook_secret: str,
    request_timeout: int,
) -> None:
    """Run Telegram webhook receiver on the container HTTP port."""
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(
        url=f"{webhook_url}{webhook_path}",
        secret_token=webhook_secret,
        request_timeout=request_timeout,
    )

    app = create_webhook_app(
        dispatcher,
        bot,
        webhook_path=webhook_path,
        webhook_secret=webhook_secret,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8080)
    try:
        await site.start()
        logger.info("Webhook server is listening on 0.0.0.0:8080")
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


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
            await run_webhook(
                bot=bot,
                dispatcher=dp,
                webhook_url=settings.telegram_webhook_url or "",
                webhook_path=settings.telegram_webhook_path,
                webhook_secret=settings.telegram_webhook_secret.get_secret_value()
                if settings.telegram_webhook_secret
                else "",
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
