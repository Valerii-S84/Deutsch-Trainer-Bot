"""Training session handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, Update

from app.bot.formatting import escape_markdown_text
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.quiz import (
    build_finish_keyboard,
    build_next_question_keyboard,
    build_question_options_keyboard,
    build_resume_keyboard,
)
from app.bot.keyboards.subscription import build_paywall_keyboard
from app.bot.texts import (
    CALLBACK_THEME_PREFIX,
    CALLBACK_TRAIN_ANSWER_PREFIX,
    CALLBACK_TRAIN_CANCEL_PREFIX,
    CALLBACK_TRAIN_NEXT_PREFIX,
    CALLBACK_TRAIN_NEW_PREFIX,
    CALLBACK_TRAIN_RESUME_PREFIX,
    LEVELS,
    TRAINING_CORRECT_ANSWER_TEXT,
    TRAINING_EXPLANATION_TEXT,
    TRAINING_FINISH_TEXT,
    TRAINING_FINISH_NEW_MISTAKES_TEXT,
    TRAINING_FINISH_RECOMMENDATION_TEXT,
    TRAINING_FINISH_WEAK_THEME_TEXT,
    TRAINING_INCORRECT_ANSWER_TEXT,
    TRAINING_QUESTION_TEMPLATE,
    TRAINING_NO_LEVEL_SELECTED_TEXT,
    TRAINING_RESUME_NO_ACTIVE_TEXT,
    TRAINING_SESSION_CANCELLED_TEXT,
    TRAINING_SESSION_COMPLETED_TEXT,
    TRAINING_SESSION_ERROR_TEXT,
    TRAINING_SESSION_RESUME_TEXT,
    TRAINING_THEME_NOT_AVAILABLE_TEXT,
    TRAINING_QUIZBANK_AUTH_ERROR_TEXT,
    TRAINING_QUIZBANK_RATE_LIMIT_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
    TRAINING_QUIZBANK_VALIDATION_TEXT,
    TRAINING_ANSWER_DUPLICATE_TEXT,
    PAYWALL_DAILY_LIMIT_TEXT,
)
from app.db.session import get_session as _get_session
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.repositories.api_error_logs import ApiErrorLogRepository
from app.repositories.users import UserRepository
from app.services.analytics import AnalyticsTracker
from app.services.training_session import (
    AnswerResult,
    ActiveSessionConflictError,
    ActiveSessionNotFoundError,
    NoMoreQuestionsError,
    QuestionStateError,
    TrainingSessionService,
)
from app.services.entitlements import DailyLimitExceededError, EntitlementService
from app.services.progress import ProgressService
from app.services.mistakes import MistakeService

router = Router(name="training")


training_service = TrainingSessionService(
    progress_service=ProgressService(),
    mistakes_service=MistakeService(),
    entitlement_service=EntitlementService(),
)
_api_error_log_repo = ApiErrorLogRepository()
_user_repo = UserRepository()
_analytics_tracker = AnalyticsTracker()


def _session_factory():
    return _get_session()


def _extract_user_id(event: Message | CallbackQuery) -> int | None:
    return getattr(getattr(event, "from_user", None), "id", None)


def _extract_update_id(event_update: Update | None) -> int | None:
    update_id = getattr(event_update, "update_id", None)
    return update_id if isinstance(update_id, int) else None


def _normalize_theme(theme: str) -> str:
    normalized = theme.strip()
    if not normalized:
        raise ValueError("invalid theme")
    return normalized


def _parse_theme_payload(data: str | None) -> tuple[str, str]:
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


def _parse_answer_payload(data: str | None) -> tuple[int, str, str]:
    if not data:
        raise ValueError("empty payload")
    payload = data.removeprefix(CALLBACK_TRAIN_ANSWER_PREFIX + ":")
    parts = payload.split(":", 2)
    if len(parts) != 3:
        raise ValueError("invalid answer payload")
    return int(parts[0]), parts[1], parts[2]


def _parse_session_payload(data: str | None, prefix: str) -> int:
    if not data or not data.startswith(prefix + ":"):
        raise ValueError("invalid payload")
    body = data.removeprefix(prefix + ":")
    session_id_str, _, _ = body.partition(":")
    if not session_id_str:
        raise ValueError("invalid payload")
    return int(session_id_str)


def _parse_next_payload(data: str | None) -> tuple[int, str]:
    if not data:
        raise ValueError("empty payload")
    payload = data.removeprefix(CALLBACK_TRAIN_NEXT_PREFIX + ":")
    session_text, _, token = payload.partition(":")
    if not session_text or not token:
        raise ValueError("invalid payload")
    return int(session_text), token


def _question_message(position: int, total_questions: int, question_text: str) -> str:
    return TRAINING_QUESTION_TEMPLATE.format(
        position=position,
        total=total_questions,
        question_text=escape_markdown_text(question_text),
    )


def _result_message(result: AnswerResult) -> str:
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


def _pending_question_token(session: object) -> str | None:
    metadata = getattr(session, "api_metadata", None) or {}
    pending = metadata.get("pending_question") if isinstance(metadata, dict) else None
    if not isinstance(pending, dict):
        return None
    token = pending.get("question_token")
    return token if isinstance(token, str) else None


def _percent_correct(correct_answers: int, total_questions: int) -> int:
    if total_questions <= 0:
        return 0
    return round((correct_answers / total_questions) * 100)


def _map_quizbank_error(error: Exception) -> str:
    if isinstance(error, QuizBankAuthError):
        return TRAINING_QUIZBANK_AUTH_ERROR_TEXT
    if isinstance(error, QuizBankRateLimitError):
        return TRAINING_QUIZBANK_RATE_LIMIT_TEXT
    if isinstance(error, QuizBankUnavailableError):
        return TRAINING_QUIZBANK_UNAVAILABLE_TEXT
    if isinstance(error, QuizBankValidationError):
        return TRAINING_QUIZBANK_VALIDATION_TEXT
    return TRAINING_SESSION_ERROR_TEXT


def _map_session_error(error: Exception) -> str:
    if isinstance(error, DailyLimitExceededError):
        return PAYWALL_DAILY_LIMIT_TEXT
    if isinstance(error, ActiveSessionNotFoundError):
        return TRAINING_SESSION_COMPLETED_TEXT
    if isinstance(error, NoMoreQuestionsError):
        return TRAINING_SESSION_COMPLETED_TEXT
    if isinstance(error, QuestionStateError):
        return TRAINING_SESSION_ERROR_TEXT
    return TRAINING_SESSION_ERROR_TEXT


def _quiz_bank_error_category(error: QuizBankError) -> str:
    if isinstance(error, QuizBankAuthError):
        return "auth"
    if isinstance(error, QuizBankRateLimitError):
        return "rate_limit"
    if isinstance(error, QuizBankValidationError):
        return "validation"
    if isinstance(error, QuizBankUnavailableError):
        return "unavailable"
    return "unknown"


async def _persist_quiz_bank_error(
    telegram_user_id: int | None,
    error: QuizBankError,
    *,
    level: str | None,
    theme: str | None,
) -> None:
    async with _session_factory() as db:
        try:
            user = await _user_repo.get_by_telegram_id(db, telegram_user_id) if telegram_user_id else None
            await _api_error_log_repo.record(
                db,
                endpoint=error.endpoint or "unknown",
                error_category=_quiz_bank_error_category(error),
                user_id=getattr(user, "id", None),
                request_id=error.request_id,
                status_code=error.status_code,
                level=level,
                theme=theme,
                error_metadata={"message": error.message},
            )
            event_name = "quiz_api_invalid_response" if isinstance(error, QuizBankValidationError) else "quiz_api_request_failed"
            await _analytics_tracker.record(
                db,
                event_name=event_name,
                user_id=getattr(user, "id", None),
                event_metadata={
                    "endpoint": error.endpoint or "unknown",
                    "error_category": _quiz_bank_error_category(error),
                    "status_code": error.status_code,
                    "level": level,
                    "theme": theme,
                },
                source="training",
            )
            await db.commit()
        except Exception:
            await db.rollback()


async def _send_daily_limit_paywall(message: Message) -> None:
    await message.answer(
        PAYWALL_DAILY_LIMIT_TEXT,
        reply_markup=build_paywall_keyboard(include_progress=True),
    )


async def _send_question(message: Message, question) -> None:
    await message.answer(
        _question_message(
            position=question.position,
            total_questions=question.total_questions,
            question_text=question.question_text,
        ),
        reply_markup=build_question_options_keyboard(question),
        parse_mode="Markdown",
    )


def _build_finish_message(correct_answers: int, total_questions: int) -> str:
    return TRAINING_FINISH_TEXT.format(
        correct=correct_answers,
        total=total_questions,
        percent=_percent_correct(correct_answers, total_questions),
    )


def _build_completed_feedback(result: AnswerResult) -> str:
    message = _result_message(result)
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


@router.callback_query(F.data.startswith(CALLBACK_THEME_PREFIX))
async def handle_theme_selected(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        level, theme = _parse_theme_payload(callback_query.data)
    except ValueError:
        callback_data = callback_query.data or ""
        if callback_data.startswith(CALLBACK_THEME_PREFIX) and (callback_data.count(":") == 1 or callback_data.startswith(f"{CALLBACK_THEME_PREFIX}:")):
            await callback_query.message.answer(TRAINING_NO_LEVEL_SELECTED_TEXT, reply_markup=build_levels_keyboard())
        else:
            await callback_query.message.answer(TRAINING_THEME_NOT_AVAILABLE_TEXT)
        return

    if level not in LEVELS:
        await callback_query.message.answer(TRAINING_THEME_NOT_AVAILABLE_TEXT)
        return

    async with _session_factory() as db:
        try:
            internal_user_id = None
            if hasattr(db, "get_bind"):
                user = await _user_repo.set_training_preferences(db, user_id, level=level, theme=theme)
                if getattr(user, "id", None) is None and hasattr(db, "flush"):
                    await db.flush()
                internal_user_id = getattr(user, "id", None)
            await _analytics_tracker.record(
                db,
                event_name="theme_selected",
                user_id=internal_user_id,
                event_metadata={"level": level, "theme": theme},
                source="onboarding",
            )
            active = await training_service.get_active_session(db, user_id)
            if active is not None:
                await db.commit()
                await callback_query.message.answer(
                    TRAINING_SESSION_RESUME_TEXT,
                    reply_markup=build_resume_keyboard(active.id),
                )
                return
            _, question = await training_service.resume_or_start_session(
                db,
                user_id,
                level=level,
                theme=theme,
                force_new=False,
                total_questions=TrainingSessionService.DEFAULT_SESSION_QUESTIONS,
            )
            await db.commit()
        except ActiveSessionConflictError:
            await callback_query.message.answer(TRAINING_SESSION_RESUME_TEXT)
            return
        except (
            QuizBankAuthError,
            QuizBankRateLimitError,
            QuizBankUnavailableError,
            QuizBankValidationError,
            NoMoreQuestionsError,
            DailyLimitExceededError,
        ) as exc:
            await db.rollback()
            if isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                if isinstance(exc, QuizBankError):
                    await _persist_quiz_bank_error(user_id, exc, level=level, theme=theme)
                await callback_query.message.answer(_map_quizbank_error(exc))
            return
        except Exception:
            await db.rollback()
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

    await _send_question(callback_query.message, question)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_RESUME_PREFIX + ":"))
async def handle_resume_training(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id = _parse_session_payload(callback_query.data, CALLBACK_TRAIN_RESUME_PREFIX)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        session = await training_service.get_active_session(db, user_id)
        if session is None or session.id != session_id:
            await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)
            return

        try:
            question = await training_service.get_or_create_current_question(db, user_id, force_refresh=False)
            await db.commit()
        except (
            ActiveSessionNotFoundError,
            NoMoreQuestionsError,
            QuestionStateError,
            QuizBankAuthError,
            QuizBankRateLimitError,
            QuizBankUnavailableError,
            QuizBankValidationError,
            DailyLimitExceededError,
        ) as exc:
            await db.rollback()
            if isinstance(
                exc,
                (
                    QuizBankAuthError,
                    QuizBankRateLimitError,
                    QuizBankUnavailableError,
                    QuizBankValidationError,
                ),
            ):
                await _persist_quiz_bank_error(
                    user_id,
                    exc,
                    level=getattr(session, "level", None),
                    theme=getattr(session, "theme", None),
                )
                await callback_query.message.answer(_map_quizbank_error(exc))
            elif isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                await callback_query.message.answer(_map_session_error(exc))
            return

    await _send_question(callback_query.message, question)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_NEW_PREFIX + ":"))
async def handle_start_new_training(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id = _parse_session_payload(callback_query.data, CALLBACK_TRAIN_NEW_PREFIX)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        active = await training_service.get_active_session(db, user_id)
        if active is None or active.id != session_id:
            await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)
            return

        try:
            await training_service.start_session(
                db,
                user_id,
                level=active.level,
                theme=active.theme,
                total_questions=TrainingSessionService.DEFAULT_SESSION_QUESTIONS,
                force_new=True,
            )
            question = await training_service.get_or_create_current_question(db, user_id, force_refresh=True)
            await db.commit()
        except (
            QuizBankAuthError,
            QuizBankRateLimitError,
            QuizBankUnavailableError,
            QuizBankValidationError,
            NoMoreQuestionsError,
            DailyLimitExceededError,
        ) as exc:
            await db.rollback()
            if isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                if isinstance(exc, QuizBankError):
                    await _persist_quiz_bank_error(
                        user_id,
                        exc,
                        level=getattr(active, "level", None),
                        theme=getattr(active, "theme", None),
                    )
                await callback_query.message.answer(_map_quizbank_error(exc))
            return
        except Exception:
            await db.rollback()
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

    await _send_question(callback_query.message, question)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_CANCEL_PREFIX + ":"))
async def handle_cancel_training(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    async with _session_factory() as db:
        try:
            session_id = _parse_session_payload(callback_query.data, CALLBACK_TRAIN_CANCEL_PREFIX)
        except ValueError:
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

        try:
            active = await training_service.get_active_session(db, user_id)
            if active is None or active.id != session_id:
                await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)
                return
            cancelled = await training_service.cancel_active_session(db, user_id)
            await db.commit()
        except Exception:
            await db.rollback()
            await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
            return

    if cancelled:
        await callback_query.message.answer(TRAINING_SESSION_CANCELLED_TEXT, reply_markup=build_levels_keyboard())
    else:
        await callback_query.message.answer(TRAINING_RESUME_NO_ACTIVE_TEXT)


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_ANSWER_PREFIX + ":"))
async def handle_submit_answer(callback_query: CallbackQuery, event_update: Update | None = None) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id, question_token, selected_option = _parse_answer_payload(callback_query.data)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        try:
            result = await training_service.submit_answer(
                db,
                user_id,
                session_id=session_id,
                question_token=question_token,
                selected_option_id=selected_option,
                telegram_update_id=_extract_update_id(event_update),
            )
            await db.commit()
        except (
            QuestionStateError,
            ActiveSessionNotFoundError,
            NoMoreQuestionsError,
        ) as exc:
            await db.rollback()
            await callback_query.message.answer(_map_session_error(exc))
            return

    response = _result_message(result)
    if result.is_completed:
        await callback_query.message.answer(
            _build_completed_feedback(result),
            reply_markup=build_finish_keyboard(),
            parse_mode="Markdown",
        )
        return

    await callback_query.message.answer(
        response,
        reply_markup=build_next_question_keyboard(
            result.session_id,
            result.question_token,
        ),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith(CALLBACK_TRAIN_NEXT_PREFIX + ":"))
async def handle_next_question(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    try:
        session_id, question_token = _parse_next_payload(callback_query.data)
    except ValueError:
        await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
        return

    async with _session_factory() as db:
        try:
            active = await training_service.get_active_session(db, user_id)
            if active is None or active.id != session_id:
                await callback_query.message.answer(TRAINING_SESSION_COMPLETED_TEXT)
                return
            if _pending_question_token(active) != question_token:
                await callback_query.message.answer(TRAINING_SESSION_ERROR_TEXT)
                return
            question = await training_service.get_next_question(
                db,
                user_id,
                session_id=session_id,
                answered_question_token=question_token,
            )
            await db.commit()
        except (
            ActiveSessionNotFoundError,
            NoMoreQuestionsError,
            QuestionStateError,
            QuizBankAuthError,
            QuizBankRateLimitError,
            QuizBankUnavailableError,
            QuizBankValidationError,
            DailyLimitExceededError,
        ) as exc:
            await db.rollback()
            if isinstance(exc, (QuizBankAuthError, QuizBankRateLimitError, QuizBankUnavailableError, QuizBankValidationError)):
                await _persist_quiz_bank_error(
                    user_id,
                    exc,
                    level=getattr(active, "level", None),
                    theme=getattr(active, "theme", None),
                )
                await callback_query.message.answer(_map_quizbank_error(exc))
            elif isinstance(exc, DailyLimitExceededError):
                await _send_daily_limit_paywall(callback_query.message)
            else:
                await callback_query.message.answer(_map_session_error(exc))
            return

    await _send_question(callback_query.message, question)
