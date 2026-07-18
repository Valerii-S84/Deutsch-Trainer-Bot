from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from redis.exceptions import RedisError

from app.config import get_settings
from app.runtime.redis import get_or_create_shared_redis_client
from app.services.training_payloads import (
    QuizQuestionPayload,
    deserialize_question_payload,
    serialize_question_payload,
)

logger = logging.getLogger(__name__)

PENDING_QUESTION_PREFIX = "dtb:training:pending_question"


async def cache_pending_question_if_enabled(payload: QuizQuestionPayload) -> None:
    settings = get_settings()
    if not settings.training_answer_cache_enabled:
        return
    redis_client = get_or_create_shared_redis_client(settings)
    key = _pending_question_key(payload.session_id, payload.question_token)
    try:
        encoded = json.dumps(
            serialize_question_payload(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await redis_client.set(key, encoded, ex=settings.training_answer_cache_ttl_seconds)
    except RedisError as exc:
        logger.warning("training answer cache write failed: %s", exc.__class__.__name__)


async def get_cached_pending_question_if_enabled(
    *,
    session_id: int,
    question_token: str,
) -> QuizQuestionPayload | None:
    return (
        await get_cached_pending_questions_if_enabled([(session_id, question_token)])
    )[0]


async def get_cached_pending_questions_if_enabled(
    keys: Sequence[tuple[int, str]],
) -> list[QuizQuestionPayload | None]:
    if not keys:
        return []
    settings = get_settings()
    if not settings.training_answer_cache_enabled:
        return [None for _key in keys]
    redis_client = get_or_create_shared_redis_client(settings)
    try:
        raw_payloads = await redis_client.mget([_pending_question_key(*key) for key in keys])
    except RedisError as exc:
        logger.warning("training answer cache read failed: %s", exc.__class__.__name__)
        return [None for _key in keys]
    return [_decode_pending_payload(raw_payload) for raw_payload in raw_payloads]


def _decode_pending_payload(raw_payload: object) -> QuizQuestionPayload | None:
    if not raw_payload:
        return None
    try:
        decoded = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.warning("training answer cache payload invalid: %s", exc.__class__.__name__)
        return None
    if not isinstance(decoded, dict):
        logger.warning("training answer cache payload invalid: non-object")
        return None
    return deserialize_question_payload(decoded)


async def delete_cached_pending_question_if_enabled(
    *,
    session_id: int,
    question_token: str,
) -> None:
    settings = get_settings()
    if not settings.training_answer_cache_enabled:
        return
    redis_client = get_or_create_shared_redis_client(settings)
    try:
        await redis_client.delete(_pending_question_key(session_id, question_token))
    except RedisError as exc:
        logger.warning("training answer cache delete failed: %s", exc.__class__.__name__)


def _pending_question_key(session_id: int, question_token: str) -> str:
    return f"{PENDING_QUESTION_PREFIX}:{session_id}:{question_token}"
