"""Review handlers for mistake replay flow."""

from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.formatting import escape_markdown_text
from app.bot.keyboards.main_menu import build_back_to_main_menu_button
from app.bot.keyboards.quiz import build_question_options_keyboard
from app.bot.keyboards.review import build_review_empty_keyboard
from app.bot.texts import (
    CALLBACK_REVIEW,
    REVIEW_EMPTY_STATE_TEXT,
    TRAINING_QUIZBANK_AUTH_ERROR_TEXT,
    TRAINING_QUIZBANK_RATE_LIMIT_TEXT,
    TRAINING_QUIZBANK_UNAVAILABLE_TEXT,
    TRAINING_QUIZBANK_VALIDATION_TEXT,
    TRAINING_QUESTION_TEMPLATE,
    TRAINING_SESSION_ERROR_TEXT,
    TRAINING_SESSION_RESUME_TEXT,
)
from app.db.session import get_session as _get_session
from app.quiz_bank.errors import (
    QuizBankAuthError,
    QuizBankRateLimitError,
    QuizBankUnavailableError,
    QuizBankValidationError,
)
from app.services.mistakes import MistakeService
from app.services.training_session import (
    ActiveSessionConflictError,
    NoMoreQuestionsError,
    NoReviewItemsError,
    TrainingSessionService,
)


router = Router(name="review")

review_service = TrainingSessionService(mistakes_service=MistakeService())


def _extract_user_id(event: CallbackQuery) -> int | None:
    return getattr(getattr(event, "from_user", None), "id", None)


def _session_factory():
    return _get_session()


def _question_message(position: int, total_questions: int, question_text: str) -> str:
    return TRAINING_QUESTION_TEMPLATE.format(
        position=position,
        total=total_questions,
        question_text=escape_markdown_text(question_text),
    )


@asynccontextmanager
async def _session_context():
    db = _session_factory()
    if hasattr(db, "__aenter__") and hasattr(db, "__aexit__"):
        async with db as session:
            yield session
    else:
        try:
            yield db
        except Exception:
            if hasattr(db, "rollback"):
                await db.rollback()
            raise


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


@router.callback_query(F.data == CALLBACK_REVIEW)
async def handle_review_entry(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is None:
        return

    user_id = _extract_user_id(callback_query)
    if not user_id:
        return

    async with _session_context() as db:
        try:
            _, question = await review_service.resume_or_start_review_session(
                db,
                user_id,
                force_new=False,
                total_questions=TrainingSessionService.DEFAULT_SESSION_QUESTIONS,
            )
            await db.commit()
        except NoReviewItemsError:
            await db.rollback()
            await callback_query.message.answer(
                REVIEW_EMPTY_STATE_TEXT,
                reply_markup=build_review_empty_keyboard(),
            )
            return
        except ActiveSessionConflictError:
            await db.rollback()
            await callback_query.message.answer(
                TRAINING_SESSION_RESUME_TEXT,
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        except NoMoreQuestionsError:
            await db.rollback()
            await callback_query.message.answer(
                TRAINING_SESSION_ERROR_TEXT,
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        except (
            QuizBankAuthError,
            QuizBankRateLimitError,
            QuizBankUnavailableError,
            QuizBankValidationError,
        ) as exc:
            await db.rollback()
            await callback_query.message.answer(
                _map_quizbank_error(exc),
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        except Exception:
            await db.rollback()
            await callback_query.message.answer(
                TRAINING_SESSION_ERROR_TEXT,
                reply_markup=build_back_to_main_menu_button(),
            )
            return

    await callback_query.message.answer(
        _question_message(
            position=question.position,
            total_questions=question.total_questions,
            question_text=question.question_text,
        ),
        reply_markup=build_question_options_keyboard(question),
        parse_mode="Markdown",
    )
