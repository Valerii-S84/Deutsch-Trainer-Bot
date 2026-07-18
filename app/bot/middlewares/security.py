"""Security middleware for Telegram update boundaries."""

from __future__ import annotations

import logging
from inspect import isawaitable
from typing import Any

from app.bot.texts import (
    CALLBACK_PAYMENT_PLAN_PREFIX,
    CALLBACK_REVIEW,
    CALLBACK_REVIEW_START,
    CALLBACK_SUBSCRIPTION,
    CALLBACK_THEME_PREFIX,
    CALLBACK_TRAIN_ANSWER_PREFIX,
    CALLBACK_TRAIN_NEXT_PREFIX,
    CALLBACK_TRAIN_NEW_PREFIX,
    CALLBACK_TRAIN_RESUME_PREFIX,
    RATE_LIMIT_HIT_TEXT,
)
from app.security.rate_limits import (
    ACTION_ADMIN,
    ACTION_ANSWER,
    ACTION_PAYMENT_START,
    ACTION_PAYWALL_CLICK,
    ACTION_RETRY,
    ACTION_START,
    ACTION_TRAINING_START,
    DuplicateUpdateGuard,
    InMemoryRateLimiter,
    RateLimitBackendError,
)
from app.runtime.webhook_profiling import (
    record_webhook_metric,
    webhook_operation_label,
    webhook_timing_span,
)

logger = logging.getLogger(__name__)


class SecurityMiddleware:
    """Validate update identity, drop duplicates and rate-limit abuse-sensitive actions."""

    def __init__(
        self,
        *,
        rate_limiter: Any | None = None,
        duplicate_guard: Any | None = None,
        rate_limit_enabled: bool = True,
    ) -> None:
        self._rate_limiter = rate_limiter or InMemoryRateLimiter()
        self._duplicate_guard = duplicate_guard or DuplicateUpdateGuard()
        self._rate_limit_enabled = rate_limit_enabled

    async def __call__(self, handler: Any, event: Any, data: dict[str, Any]) -> Any:
        update = data.get("event_update") or event
        update_id = _update_id(update)
        if not data.get("skip_duplicate_guard") and not await self._accept_update(update, update_id):
            return None

        if data.get("skip_rate_limit") or not self._rate_limit_enabled:
            return await handler(event, data)

        action = _action_from_update(update)
        if action is None:
            return await handler(event, data)

        identity = _rate_limit_identity(update)
        decision = await self._check_rate_limit(action=action, identity=identity, update=update, update_id=update_id)
        if decision is None:
            return None
        if decision.allowed:
            return await handler(event, data)

        logger.info(
            "telegram rate limit hit: action=%s identity=%s update_id=%s retry_after=%s",
            action,
            identity,
            update_id,
            decision.retry_after_seconds,
        )
        await _notify_rate_limit(update)
        return None

    async def _accept_update(self, update: Any, update_id: int | None) -> bool:
        try:
            accepted = await self._check_duplicate_guard(update_id)
        except RateLimitBackendError:
            logger.warning("telegram security state backend unavailable: update_id=%s", update_id)
            await _notify_rate_limit(update)
            return False
        if accepted:
            return True
        logger.info("duplicate telegram update ignored: update_id=%s", update_id)
        return False

    async def _check_duplicate_guard(self, update_id: int | None) -> bool:
        with webhook_timing_span("middleware.security_duplicate_guard_ms"):
            record_webhook_metric("duplicate_guard.call_count", 1)
            with webhook_operation_label("duplicate_guard.redis"):
                return bool(await _maybe_await(self._duplicate_guard.accept(update_id)))

    async def _check_rate_limit(self, *, action: str, identity: str, update: Any, update_id: int | None) -> Any | None:
        try:
            with webhook_timing_span("middleware.security_rate_limit_ms"):
                with webhook_operation_label("rate_limit.redis"):
                    return await _maybe_await(self._rate_limiter.check(action=action, identity=identity))
        except RateLimitBackendError:
            logger.warning(
                "telegram rate limit backend unavailable: action=%s identity=%s update_id=%s",
                action,
                identity,
                update_id,
            )
            await _notify_rate_limit(update)
            return None


def _update_id(update: Any) -> int | None:
    update_id = getattr(update, "update_id", None)
    return update_id if isinstance(update_id, int) else None


def _rate_limit_identity(update: Any) -> str:
    user_id = _telegram_user_id(update)
    if user_id is not None:
        return f"user:{user_id}"
    chat_id = _chat_id(update)
    if chat_id is not None:
        return f"chat:{chat_id}"
    update_id = _update_id(update)
    if update_id is not None:
        return f"update:{update_id}"
    return "anonymous"


def _telegram_user_id(update: Any) -> int | None:
    user = getattr(_primary_event(update), "from_user", None)
    user_id = getattr(user, "id", None)
    return user_id if isinstance(user_id, int) else None


def _chat_id(update: Any) -> int | None:
    chat = getattr(_message(update), "chat", None)
    chat_id = getattr(chat, "id", None)
    return chat_id if isinstance(chat_id, int) else None


def _action_from_update(update: Any) -> str | None:
    text = _message_text(update)
    if text:
        command = text.split(maxsplit=1)[0]
        if command == "/start":
            return ACTION_START
        if command == "/admin_metrics":
            return ACTION_ADMIN

    pre_checkout = _pre_checkout_query(update)
    if pre_checkout is not None:
        return ACTION_PAYMENT_START

    callback = _callback_query(update)
    data = getattr(callback, "data", None)
    if not isinstance(data, str):
        return None
    return _callback_action(data)


def _callback_action(data: str) -> str | None:
    if data.startswith(CALLBACK_PAYMENT_PLAN_PREFIX):
        return ACTION_PAYMENT_START
    if data == CALLBACK_SUBSCRIPTION:
        return ACTION_PAYWALL_CLICK
    if data.startswith(CALLBACK_THEME_PREFIX) or data.startswith(CALLBACK_TRAIN_NEW_PREFIX + ":"):
        return ACTION_TRAINING_START
    if data == CALLBACK_REVIEW_START or data == CALLBACK_REVIEW:
        return ACTION_TRAINING_START
    if data.startswith(CALLBACK_TRAIN_ANSWER_PREFIX + ":"):
        return ACTION_ANSWER
    if data.startswith(CALLBACK_TRAIN_NEXT_PREFIX + ":") or data.startswith(CALLBACK_TRAIN_RESUME_PREFIX + ":"):
        return ACTION_RETRY
    return None


def _message_text(update: Any) -> str | None:
    text = getattr(_message(update), "text", None)
    return text.strip() if isinstance(text, str) else None


def _primary_event(update: Any) -> Any:
    return _message(update) or _callback_query(update) or _pre_checkout_query(update) or update


def _message(update: Any) -> Any:
    return getattr(update, "message", None) or _direct_event(update, "text")


def _callback_query(update: Any) -> Any:
    return getattr(update, "callback_query", None) or _direct_event(update, "data")


def _pre_checkout_query(update: Any) -> Any:
    return getattr(update, "pre_checkout_query", None) or _direct_event(update, "invoice_payload")


def _direct_event(update: Any, marker: str) -> Any:
    return update if hasattr(update, marker) and hasattr(update, "from_user") else None


async def _notify_rate_limit(update: Any) -> None:
    pre_checkout = _pre_checkout_query(update)
    if pre_checkout is not None and hasattr(pre_checkout, "answer"):
        await pre_checkout.answer(ok=False, error_message=RATE_LIMIT_HIT_TEXT)
        return

    callback = _callback_query(update)
    if callback is not None and hasattr(callback, "answer"):
        await callback.answer(RATE_LIMIT_HIT_TEXT, show_alert=False)
        return

    message = _message(update)
    if message is not None and hasattr(message, "answer"):
        await message.answer(RATE_LIMIT_HIT_TEXT)


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value
