from __future__ import annotations

from time import perf_counter

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

from app.runtime.webhook_profiling import (
    WebhookProfileCollector,
    begin_webhook_timing,
    end_webhook_timing,
    webhook_timing_span,
)


class ProfiledSimpleRequestHandler(SimpleRequestHandler):
    def __init__(
        self,
        dispatcher: Dispatcher,
        bot: Bot,
        *,
        profiler: WebhookProfileCollector,
        handle_in_background: bool = True,
        secret_token: str | None = None,
        **data,
    ) -> None:
        super().__init__(
            dispatcher=dispatcher,
            bot=bot,
            handle_in_background=handle_in_background,
            secret_token=secret_token,
            **data,
        )
        self._profiler = profiler

    async def _handle_request(self, bot: Bot, request: web.Request) -> web.Response:
        with webhook_timing_span("webhook.request_json_ms"):
            update = await request.json(loads=bot.session.json_loads)
        with webhook_timing_span("webhook.dispatch_ms"):
            result = await self.dispatcher.feed_webhook_update(
                bot,
                update,
                **self.data,
            )
        with webhook_timing_span("webhook.response_build_ms"):
            return web.Response(body=self._build_response_writer(bot=bot, result=result))

    async def handle(self, request: web.Request) -> web.Response:
        total_started = perf_counter()
        timings, metrics, token = begin_webhook_timing()
        status_code = 500
        try:
            with webhook_timing_span("webhook.resolve_bot_ms"):
                bot = await self.resolve_bot(request)
            with webhook_timing_span("webhook.verify_secret_ms"):
                is_valid = self.verify_secret(
                    request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""),
                    bot,
                )
            if not is_valid:
                status_code = 401
                return web.Response(body="Unauthorized", status=401)
            if self.handle_in_background:
                with webhook_timing_span("webhook.background_response_ms"):
                    response = await self._handle_request_background(bot=bot, request=request)
            else:
                response = await self._handle_request(bot=bot, request=request)
            status_code = response.status
            return response
        finally:
            total_ms = (perf_counter() - total_started) * 1000
            end_webhook_timing(token)
            self._profiler.record_request(
                request_path=request.path,
                status_code=status_code,
                total_ms=total_ms,
                spans_ms=timings,
                metrics=metrics,
            )
