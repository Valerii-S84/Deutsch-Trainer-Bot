from __future__ import annotations

from typing import Any, Callable

from aiogram.types import CallbackQuery, Message, Update

from app.bot.formatting import escape_markdown_text
from app.bot.keyboards.quiz import (
    build_finish_keyboard,
    build_next_question_keyboard,
    build_question_options_keyboard,
)
from app.bot.keyboards.subscription import build_paywall_keyboard
from app.bot.texts import (
    CALLBACK_TRAIN_ANSWER_PREFIX,
    CALLBACK_TRAIN_CANCEL_PREFIX,
    CALLBACK_TRAIN_NEXT_PREFIX,
    CALLBACK_TRAIN_NEW_PREFIX,
    CALLBACK_TRAIN_RESUME_PREFIX,
    CALLBACK_THEME_PREFIX,
    PAYWALL_DAILY_LIMIT_TEXT,
    TRAINING_ANSWER_DUPLICATE_TEXT,
    TRAINING_CORRECT_ANSWER_TEXT,
    TRAINING_EXPLANATION_TEXT,
    TRAINING_FINISH_NEW_MISTAKES_TEXT,
    TRAINING_FINISH_RECOMMENDATION_TEXT,
    TRAINING_FINISH_TEXT,
    TRAINING_FINISH_WEAK_THEME_TEXT,
    TRAINING_INCORRECT_ANSWER_TEXT,
    TRAINING_QUESTION_TEMPLATE,
    TRAINING_QUIZBANK_AUTH_ERROR_TEXT,
    TRAINING_QUIZBANK_RATE_LIMIT_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
    TRAINING_QUIZBANK_VALIDATION_TEXT,
    TRAINING_SESSION_COMPLETED_TEXT,
    TRAINING_SESSION_ERROR_TEXT,
)
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.services.entitlements import DailyLimitExceededError
from app.services.training_payloads import (
    ActiveSessionNotFoundError,
    AnswerResult,
    NoMoreQuestionsError,
    QuestionStateError,
)


def extract_user_id(event: Message | CallbackQuery) -> int | None:
    return getattr(getattr(event, "from_user", None), "id", None)


def extract_update_id(event_update: Update | None) -> int | None:
    update_id = getattr(event_update, "update_id", None)
    return update_id if isinstance(update_id, int) else None


def parse_theme_payload(data: str | None) -> tuple[str, str]:
    if not data or not data.startswith(CALLBACK_THEME_PREFIX):
        raise ValueError("invalid payload")

    payload = data.removeprefix(CALLBACK_THEME_PREFIX)
    if ":" not in payload:
        raise ValueError("invalid payload")

    level, _, theme = payload.partition(":")
    if not level:
        raise ValueError("no level")
    if not theme:
        raise ValueError("invalid payload")
    return level, _normalize_theme(theme)


def parse_answer_payload(data: str | None) -> tuple[int, str, str]:
    if not data:
        raise ValueError("empty payload")
    payload = data.removeprefix(CALLBACK_TRAIN_ANSWER_PREFIX + ":")
    parts = payload.split(":", 2)
    if len(parts) != 3:
        raise ValueError("invalid answer payload")
    return int(parts[0]), parts[1], parts[2]


def parse_session_payload(data: str | None, prefix: str) -> int:
    if not data or not data.startswith(prefix + ":"):
        raise ValueError("invalid payload")
    body = data.removeprefix(prefix + ":")
    session_id_str, _, _ = body.partition(":")
    if not session_id_str:
        raise ValueError("invalid payload")
    return int(session_id_str)


def parse_next_payload(data: str | None) -> tuple[int, str]:
    if not data:
        raise ValueError("empty payload")
    payload = data.removeprefix(CALLBACK_TRAIN_NEXT_PREFIX + ":")
    session_text, _, token = payload.partition(":")
    if not session_text or not token:
        raise ValueError("invalid payload")
    return int(session_text), token


def pending_question_token(session: object) -> str | None:
    metadata = getattr(session, "api_metadata", None) or {}
    pending = metadata.get("pending_question") if isinstance(metadata, dict) else None
    if not isinstance(pending, dict):
        return None
    token = pending.get("question_token")
    return token if isinstance(token, str) else None


def map_quizbank_error(error: Exception) -> str:
    if isinstance(error, QuizBankAuthError):
        return TRAINING_QUIZBANK_AUTH_ERROR_TEXT
    if isinstance(error, QuizBankRateLimitError):
        return TRAINING_QUIZBANK_RATE_LIMIT_TEXT
    if isinstance(error, QuizBankUnavailableError):
        return TRAINING_QUIZBANK_UNAVAILABLE_TEXT
    if isinstance(error, QuizBankValidationError):
        return TRAINING_QUIZBANK_VALIDATION_TEXT
    return TRAINING_SESSION_ERROR_TEXT


def map_session_error(error: Exception) -> str:
    if isinstance(error, DailyLimitExceededError):
        return PAYWALL_DAILY_LIMIT_TEXT
    if isinstance(error, ActiveSessionNotFoundError):
        return TRAINING_SESSION_COMPLETED_TEXT
    if isinstance(error, NoMoreQuestionsError):
        return TRAINING_SESSION_COMPLETED_TEXT
    if isinstance(error, QuestionStateError):
        return TRAINING_SESSION_ERROR_TEXT
    return TRAINING_SESSION_ERROR_TEXT


async def persist_quiz_bank_error(
    session_factory: Callable[[], Any],
    user_repo: Any,
    api_error_log_repo: Any,
    analytics_tracker: Any,
    telegram_user_id: int | None,
    error: QuizBankError,
    *,
    level: str | None,
    theme: str | None,
) -> None:
    async with session_factory() as db:
        try:
            user = await user_repo.get_by_telegram_id(db, telegram_user_id) if telegram_user_id else None
            await api_error_log_repo.record(
                db,
                endpoint=error.endpoint or "unknown",
                error_category=quiz_bank_error_category(error),
                user_id=getattr(user, "id", None),
                request_id=error.request_id,
                status_code=error.status_code,
                level=level,
                theme=theme,
                error_metadata={"message": error.message},
            )
            await analytics_tracker.record(
                db,
                event_name=_quiz_bank_event_name(error),
                user_id=getattr(user, "id", None),
                event_metadata={
                    "endpoint": error.endpoint or "unknown",
                    "error_category": quiz_bank_error_category(error),
                    "status_code": error.status_code,
                    "level": level,
                    "theme": theme,
                },
                source="training",
            )
            await db.commit()
        except Exception:
            await db.rollback()


async def send_daily_limit_paywall(message: Message) -> None:
    await message.answer(
        PAYWALL_DAILY_LIMIT_TEXT,
        reply_markup=build_paywall_keyboard(include_progress=True),
    )


async def send_question(message: Message, question: Any) -> None:
    await message.answer(
        _question_message(
            position=question.position,
            total_questions=question.total_questions,
            question_text=question.question_text,
        ),
        reply_markup=build_question_options_keyboard(question),
        parse_mode="Markdown",
    )


async def send_answer_result(message: Message, result: AnswerResult) -> None:
    if result.is_completed:
        await message.answer(
            _build_completed_feedback(result),
            reply_markup=build_finish_keyboard(),
            parse_mode="Markdown",
        )
        return

    await message.answer(
        result_message(result),
        reply_markup=build_next_question_keyboard(
            result.session_id,
            result.question_token,
        ),
        parse_mode="Markdown",
    )


def result_message(result: AnswerResult) -> str:
    if result.is_correct:
        text = TRAINING_CORRECT_ANSWER_TEXT
    else:
        correct_answer = escape_markdown_text(result.correct_answer_text or result.correct_answer)
        text = TRAINING_INCORRECT_ANSWER_TEXT.format(correct_answer=correct_answer)
    if result.is_duplicate:
        text = f"{TRAINING_ANSWER_DUPLICATE_TEXT}\n\n{text}"
    if result.explanation:
        explanation = escape_markdown_text(result.explanation)
        text = f"{text}\n\n{TRAINING_EXPLANATION_TEXT.format(explanation=explanation)}"
    return text


def quiz_bank_error_category(error: QuizBankError) -> str:
    if isinstance(error, QuizBankAuthError):
        return "auth"
    if isinstance(error, QuizBankRateLimitError):
        return "rate_limit"
    if isinstance(error, QuizBankValidationError):
        return "validation"
    if isinstance(error, QuizBankUnavailableError):
        return "unavailable"
    return "unknown"


def _normalize_theme(theme: str) -> str:
    normalized = theme.strip()
    if not normalized:
        raise ValueError("invalid theme")
    return normalized


def _question_message(position: int, total_questions: int, question_text: str) -> str:
    return TRAINING_QUESTION_TEMPLATE.format(
        position=position,
        total=total_questions,
        question_text=escape_markdown_text(question_text),
    )


def _percent_correct(correct_answers: int, total_questions: int) -> int:
    if total_questions <= 0:
        return 0
    return round((correct_answers / total_questions) * 100)


def _build_finish_message(correct_answers: int, total_questions: int) -> str:
    return TRAINING_FINISH_TEXT.format(
        correct=correct_answers,
        total=total_questions,
        percent=_percent_correct(correct_answers, total_questions),
    )


def _build_completed_feedback(result: AnswerResult) -> str:
    message = result_message(result)
    finish = _build_finish_message(result.correct_answers, result.total_questions)
    details: list[str] = []
    if result.new_mistakes_count:
        details.append(TRAINING_FINISH_NEW_MISTAKES_TEXT.format(count=result.new_mistakes_count))
    if result.weak_theme:
        details.append(TRAINING_FINISH_WEAK_THEME_TEXT.format(theme=escape_markdown_text(result.weak_theme)))
    if result.recommendation_text:
        details.append(
            TRAINING_FINISH_RECOMMENDATION_TEXT.format(
                recommendation=escape_markdown_text(result.recommendation_text),
            ),
        )
    if details:
        finish = f"{finish}\n" + "\n".join(details)
    return f"{message}\n\n{finish}"


def _quiz_bank_event_name(error: QuizBankError) -> str:
    if isinstance(error, QuizBankValidationError):
        return "quiz_api_invalid_response"
    return "quiz_api_request_failed"
