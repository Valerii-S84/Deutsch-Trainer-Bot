from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import app.bot.texts as bot_texts
from app.bot.handlers.profile import _format_limited_progress_text, _format_progress_text
from app.bot.handlers.subscription import _format_subscription_text
from app.bot.handlers.training_flow import _build_completed_feedback, result_message
from app.bot.keyboards.levels import build_levels_keyboard
from app.bot.keyboards.main_menu import build_main_menu_keyboard, build_progress_navigation_keyboard
from app.bot.keyboards.quiz import (
    build_finish_keyboard,
    build_next_question_keyboard,
    build_question_options_keyboard,
    build_resume_keyboard,
)
from app.bot.keyboards.review import build_review_empty_keyboard, build_review_screen_keyboard
from app.bot.keyboards.subscription import build_invoice_payment_keyboard
from app.bot.keyboards.subscription import build_payment_failure_keyboard, build_payment_success_keyboard
from app.bot.keyboards.subscription import build_paywall_keyboard, build_subscription_keyboard
from app.config import Settings
from app.services.analytics import (
    AdminMetricsSnapshot,
    ConversionMetrics,
    DailyAdminMetrics,
    RateMetric,
    RetentionMetrics,
    format_admin_metrics,
)
from app.services.entitlements import PLAN_PLUS, PLAN_PRO
from app.services.payments import PaymentService
from app.services.training_session import AnswerResult, QuizQuestionPayload


TEXTS_PATH = Path("app/bot/texts.py")
BOT_DIR = Path("app/bot")
KEYBOARDS_DIR = Path("app/bot/keyboards")
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
FORBIDDEN_ENGLISH_RE = re.compile(
    r"\b(?:please|try again|payment|paywall|subscription|progress|mistakes|main menu|continue|cancel|retry|unknown|invalid|failed|success|error|free|level|invoice)\b",
    re.IGNORECASE,
)
USER_COPY_SUFFIXES = ("_TEXT", "_PROMPT", "_HEADER", "_BUTTON_TEXT")
TELEGRAM_OUTPUT_METHODS = {
    "answer",
    "answer_invoice",
    "edit_text",
    "send_invoice",
    "send_message",
}
TELEGRAM_TEXT_KEYWORDS = {"text", "title", "description", "error_message"}


def test_bot_text_constants_are_german_only_copy() -> None:
    findings = [
        f"{name}: {text}"
        for name, text in iter_bot_text_constants()
        if CYRILLIC_RE.search(text) or has_forbidden_english_ui_term(text)
    ]

    assert findings == []


def test_keyboard_literal_button_text_is_german_only_copy() -> None:
    findings = [
        f"{path}:{line}: {text}"
        for path, line, text in iter_keyboard_text_literals()
        if CYRILLIC_RE.search(text) or FORBIDDEN_ENGLISH_RE.search(text)
    ]

    assert findings == []


def test_user_facing_telegram_copy_has_no_cyrillic() -> None:
    findings = [
        f"{source}: {text}"
        for source, text in iter_user_facing_copy_samples()
        if CYRILLIC_RE.search(text)
    ]

    assert findings == []


def test_user_facing_telegram_copy_avoids_english_ui_terms() -> None:
    findings = [
        f"{source}: {text}"
        for source, text in iter_user_facing_copy_samples()
        if has_forbidden_english_ui_term(text)
    ]

    assert findings == []


def test_payment_invoice_copy_and_pay_button_are_german() -> None:
    samples = dict(iter_payment_invoice_copy_samples())

    assert samples["plus.title"] == "Plus aktivieren"
    assert samples["plus.price_label"] == "Plus-Abo"
    assert samples["plus.pay_button"] == "Bezahlen ⭐ 100"
    assert samples["pro.title"] == "Pro aktivieren"
    assert samples["pro.price_label"] == "Pro-Abo"
    assert samples["pro.pay_button"] == "Bezahlen ⭐ 250"


def test_rendered_core_telegram_scenarios_are_german_only() -> None:
    findings = [
        f"{source}: {text}"
        for source, text in iter_rendered_telegram_scenario_samples()
        if CYRILLIC_RE.search(text) or has_forbidden_english_ui_term(text)
    ]

    assert findings == []


def iter_bot_text_constants() -> tuple[tuple[str, str], ...]:
    constants: list[tuple[str, str]] = []
    for name in dir(bot_texts):
        if not is_user_copy_constant(name):
            continue
        value = getattr(bot_texts, name)
        if isinstance(value, str):
            constants.append((name, value))
    return tuple(constants)


def is_user_copy_constant(name: str) -> bool:
    return name.startswith("MENU_BUTTON_") or name.endswith(USER_COPY_SUFFIXES)


def has_forbidden_english_ui_term(text: str) -> bool:
    copy_without_format_fields = re.sub(r"\{[^{}]+\}", "", text)
    return bool(FORBIDDEN_ENGLISH_RE.search(copy_without_format_fields))


def iter_user_facing_copy_samples() -> tuple[tuple[str, str], ...]:
    samples: list[tuple[str, str]] = []
    samples.extend((f"bot_texts.{name}", text) for name, text in iter_bot_text_constants())
    samples.extend(
        (f"{path}:{line}", text)
        for path, line, text in iter_keyboard_text_literals()
    )
    samples.extend(
        (f"{path}:{line}", text)
        for path, line, text in iter_telegram_output_literals()
    )
    samples.extend(iter_payment_invoice_copy_samples())
    samples.extend(iter_admin_metrics_copy_samples())
    samples.extend(iter_rendered_telegram_scenario_samples())
    return tuple(samples)


def iter_keyboard_text_literals() -> tuple[tuple[Path, int, str], ...]:
    literals: list[tuple[Path, int, str]] = []
    for path in sorted(KEYBOARDS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            literals.extend(extract_text_keyword_literals(path, node))
    return tuple(literals)


def iter_telegram_output_literals() -> tuple[tuple[Path, int, str], ...]:
    literals: list[tuple[Path, int, str]] = []
    for path in sorted(BOT_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            literals.extend(extract_telegram_output_literals(path, node))
    return tuple(literals)


def extract_telegram_output_literals(path: Path, node: ast.AST) -> tuple[tuple[Path, int, str], ...]:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return ()
    if node.func.attr not in TELEGRAM_OUTPUT_METHODS:
        return ()

    literals: list[tuple[Path, int, str]] = []
    if node.args:
        literals.extend((path, line, text) for line, text in extract_string_fragments(node.args[0]))
    for keyword in node.keywords:
        if keyword.arg in TELEGRAM_TEXT_KEYWORDS:
            literals.extend((path, line, text) for line, text in extract_string_fragments(keyword.value))
    return tuple(literals)


def extract_string_fragments(node: ast.AST) -> tuple[tuple[int, str], ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ((node.lineno, node.value),)
    if isinstance(node, ast.JoinedStr):
        return tuple(
            (value.lineno, value.value)
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
    return ()


def extract_text_keyword_literals(path: Path, node: ast.AST) -> tuple[tuple[Path, int, str], ...]:
    if not isinstance(node, ast.Call):
        return ()
    literals: list[tuple[Path, int, str]] = []
    for keyword in node.keywords:
        if keyword.arg != "text":
            continue
        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            literals.append((path, keyword.value.lineno, keyword.value.value))
    return tuple(literals)


def iter_payment_invoice_copy_samples() -> tuple[tuple[str, str], ...]:
    service = PaymentService(settings=_payment_settings())
    samples: list[tuple[str, str]] = []
    for plan in (PLAN_PLUS, PLAN_PRO):
        config = service._plan_config(plan)
        markup = build_invoice_payment_keyboard(amount_stars=config.amount_stars)
        pay_button = markup.inline_keyboard[0][0]
        samples.extend(
            (
                (f"{plan}.title", config.title),
                (f"{plan}.description", config.description),
                (f"{plan}.price_label", f"{config.plan.capitalize()}-Abo"),
                (f"{plan}.pay_button", pay_button.text),
            ),
        )
    return tuple(samples)


def iter_admin_metrics_copy_samples() -> tuple[tuple[str, str], ...]:
    return (("admin_metrics", format_admin_metrics(_admin_metrics_snapshot())),)


def iter_rendered_telegram_scenario_samples() -> tuple[tuple[str, str], ...]:
    samples: list[tuple[str, str]] = []
    samples.extend(iter_start_and_menu_samples())
    samples.extend(iter_subscription_samples())
    samples.extend(iter_payment_flow_samples())
    samples.extend(iter_paywall_samples())
    samples.extend(iter_quiz_flow_samples())
    samples.extend(iter_profile_and_statistics_samples())
    samples.extend(iter_review_samples())
    samples.extend(iter_error_state_samples())
    return tuple(samples)


def iter_start_and_menu_samples() -> tuple[tuple[str, str], ...]:
    samples = [
        ("/start.new_user", bot_texts.TRAINING_PROMPT),
        ("/start.returning_user", f"{bot_texts.WELCOME_TEXT}\n\nHallo *Anna*! {bot_texts.MENU_PROMPT}"),
        ("main_menu.message", f"{bot_texts.MENU_PROMPT}\n\n{bot_texts.HOME_TEXT}"),
    ]
    samples.extend(keyboard_button_text_samples("main_menu", build_main_menu_keyboard()))
    samples.extend(keyboard_button_text_samples("levels", build_levels_keyboard()))
    samples.extend(keyboard_button_text_samples("progress_navigation", build_progress_navigation_keyboard()))
    return tuple(samples)


def iter_subscription_samples() -> tuple[tuple[str, str], ...]:
    samples = [
        (
            "subscription.free",
            _format_subscription_text(
                access_plan=bot_texts.SUBSCRIPTION_STATUS_FREE_TEXT,
                status=bot_texts.SUBSCRIPTION_STATUS_INACTIVE_TEXT,
            ),
        ),
        (
            "subscription.active",
            _format_subscription_text(
                access_plan="Plus",
                status=bot_texts.SUBSCRIPTION_STATUS_ACTIVE_TEXT.format(plan="Plus", expires_at="20.05.2026"),
            ),
        ),
        (
            "subscription.pending",
            _format_subscription_text(
                access_plan=bot_texts.SUBSCRIPTION_STATUS_FREE_TEXT,
                status=bot_texts.SUBSCRIPTION_STATUS_PENDING_TEXT.format(plan="Pro"),
            ),
        ),
        (
            "subscription.expired",
            _format_subscription_text(
                access_plan=bot_texts.SUBSCRIPTION_STATUS_FREE_TEXT,
                status=bot_texts.SUBSCRIPTION_STATUS_EXPIRED_TEXT.format(plan="Plus", expires_at="14.05.2026"),
            ),
        ),
    ]
    samples.extend(keyboard_button_text_samples("subscription", build_subscription_keyboard()))
    return tuple(samples)


def iter_payment_flow_samples() -> tuple[tuple[str, str], ...]:
    samples = [
        ("payment.config_required", bot_texts.PAYMENT_CONFIG_REQUIRED_TEXT),
        ("payment.precheckout_error", bot_texts.PAYMENT_PRECHECKOUT_ERROR_TEXT),
        ("payment.success_plus", bot_texts.PAYMENT_SUCCESS_PLUS_TEXT),
        ("payment.success_pro", bot_texts.PAYMENT_SUCCESS_PRO_TEXT),
        ("payment.failure", bot_texts.PAYMENT_FAILURE_TEXT),
    ]
    samples.extend(iter_payment_invoice_copy_samples())
    samples.extend(keyboard_button_text_samples("payment_success", build_payment_success_keyboard()))
    samples.extend(keyboard_button_text_samples("payment_failure", build_payment_failure_keyboard()))
    return tuple(samples)


def iter_paywall_samples() -> tuple[tuple[str, str], ...]:
    samples = [
        ("paywall.daily_limit", bot_texts.PAYWALL_DAILY_LIMIT_TEXT),
        ("paywall.progress", bot_texts.PAYWALL_PROGRESS_TEXT),
        ("paywall.mistake_repeat", bot_texts.PAYWALL_MISTAKE_REPEAT_TEXT),
    ]
    samples.extend(keyboard_button_text_samples("paywall", build_paywall_keyboard(include_progress=True)))
    return tuple(samples)


def iter_quiz_flow_samples() -> tuple[tuple[str, str], ...]:
    question = _quiz_question_payload()
    correct_result = _answer_result(is_correct=True, is_completed=False, is_duplicate=False)
    duplicate_result = _answer_result(is_correct=True, is_completed=False, is_duplicate=True)
    completed_result = _answer_result(is_correct=False, is_completed=True, is_duplicate=False)
    samples = [
        (
            "quiz.question",
            bot_texts.TRAINING_QUESTION_TEMPLATE.format(
                position=question.position,
                total=question.total_questions,
                question_text=question.question_text,
            ),
        ),
        ("quiz.correct_result", result_message(correct_result)),
        ("quiz.duplicate_result", result_message(duplicate_result)),
        ("quiz.completed_result", _build_completed_feedback(completed_result)),
        ("quiz.resume", bot_texts.TRAINING_SESSION_RESUME_TEXT),
    ]
    samples.extend(keyboard_button_text_samples("quiz.options", build_question_options_keyboard(question)))
    samples.extend(keyboard_button_text_samples("quiz.next", build_next_question_keyboard(10, "tok12345")))
    samples.extend(keyboard_button_text_samples("quiz.finish", build_finish_keyboard()))
    samples.extend(keyboard_button_text_samples("quiz.resume", build_resume_keyboard(10)))
    return tuple(samples)


def iter_profile_and_statistics_samples() -> tuple[tuple[str, str], ...]:
    rows = [_progress_record()]
    return (
        ("profile.empty", _format_progress_text([], recommendation_text=None)),
        ("profile.full", _format_progress_text(rows, recommendation_text="Übe Dativ heute noch einmal.")),
        ("profile.limited", _format_limited_progress_text(rows)),
        *iter_admin_metrics_copy_samples(),
    )


def iter_review_samples() -> tuple[tuple[str, str], ...]:
    samples = [
        ("review.empty", bot_texts.REVIEW_EMPTY_STATE_TEXT),
        ("review.screen", bot_texts.REVIEW_SCREEN_TEXT),
    ]
    samples.extend(keyboard_button_text_samples("review.empty", build_review_empty_keyboard()))
    samples.extend(keyboard_button_text_samples("review.screen", build_review_screen_keyboard()))
    return tuple(samples)


def iter_error_state_samples() -> tuple[tuple[str, str], ...]:
    return (
        ("fallback.message", bot_texts.UNKNOWN_MESSAGE_TEXT),
        ("fallback.callback", bot_texts.UNKNOWN_CALLBACK_TEXT),
        ("rate_limit", bot_texts.RATE_LIMIT_HIT_TEXT),
        ("level.invalid", bot_texts.LEVEL_CALLBACK_FALLBACK_TEXT),
        ("theme.invalid", bot_texts.THEME_CALLBACK_FALLBACK_TEXT),
        ("training.no_level", bot_texts.TRAINING_NO_LEVEL_SELECTED_TEXT),
        ("training.theme_unavailable", bot_texts.TRAINING_THEME_NOT_AVAILABLE_TEXT),
        ("training.session_error", bot_texts.TRAINING_SESSION_ERROR_TEXT),
        ("quizbank.auth", bot_texts.TRAINING_QUIZBANK_AUTH_ERROR_TEXT),
        ("quizbank.rate_limit", bot_texts.TRAINING_QUIZBANK_RATE_LIMIT_TEXT),
        ("quizbank.unavailable", bot_texts.TRAINING_QUIZBANK_UNAVAILABLE_TEXT),
        ("quizbank.validation", bot_texts.TRAINING_QUIZBANK_VALIDATION_TEXT),
        ("admin.unauthorized", bot_texts.ADMIN_METRICS_UNAUTHORIZED_TEXT),
        ("admin.unavailable", bot_texts.ADMIN_METRICS_UNAVAILABLE_TEXT),
    )


def keyboard_button_text_samples(source: str, markup) -> list[tuple[str, str]]:
    return [
        (f"{source}.button", button.text)
        for row in markup.inline_keyboard
        for button in row
    ]


def _payment_settings() -> Settings:
    return Settings(
        PLUS_PRICE_STARS="100",
        PRO_PRICE_STARS="250",
        PLUS_DURATION_DAYS=30,
        PRO_DURATION_DAYS=90,
        FREE_DAILY_QUESTION_LIMIT=1,
        PLUS_DAILY_QUESTION_LIMIT=3,
        PRO_DAILY_QUESTION_LIMIT=5,
    )


def _quiz_question_payload() -> QuizQuestionPayload:
    return QuizQuestionPayload(
        session_id=10,
        question_token="tok12345",
        question_id="q1",
        question_text="Was ist richtig?",
        answer_options=(("a", "Antwort A"), ("b", "Antwort B")),
        correct_answer="a",
        explanation="Das Verb steht an Position zwei.",
        position=1,
        total_questions=3,
        level="A1",
        theme="Alltag",
    )


def _answer_result(*, is_correct: bool, is_completed: bool, is_duplicate: bool) -> AnswerResult:
    return AnswerResult(
        selected_answer="a",
        correct_answer="a",
        correct_answer_text="Antwort A",
        question_token="tok12345",
        is_correct=is_correct,
        is_duplicate=is_duplicate,
        is_completed=is_completed,
        explanation="Das Verb steht an Position zwei.",
        correct_answers=2,
        total_questions=3,
        session_id=10,
        new_mistakes_count=1 if is_completed else 0,
        weak_theme="Dativ" if is_completed else None,
        recommendation_text="Übe Dativ heute noch einmal." if is_completed else None,
    )


def _progress_record() -> SimpleNamespace:
    return SimpleNamespace(
        topic_status="weak",
        level="A1",
        theme="Dativ",
        total_correct=2,
        total_answered=4,
        accuracy=50,
        coverage_score=20,
        coverage_status="known",
        unique_items_seen=2,
        available_items_count=10,
        stability_score=30,
        weakness_score=70,
    )


def _admin_metrics_snapshot() -> AdminMetricsSnapshot:
    zero = RateMetric(numerator=0, denominator=0, rate=None)
    return AdminMetricsSnapshot(
        generated_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        daily=DailyAdminMetrics(
            total_users=1,
            new_users_today=1,
            active_users_today=1,
            training_sessions_today=1,
            answers_today=1,
            session_completion_rate_today=RateMetric(1, 1, 1.0),
            progress_opened_today=1,
            mistakes_repeated_today=1,
            active_subscriptions=1,
            payment_errors_today=1,
            api_errors_today=1,
        ),
        conversion=ConversionMetrics(
            paywall_ctr_today=RateMetric(1, 1, 1.0),
            payment_success_rate_today=RateMetric(1, 1, 1.0),
            free_to_plus_today=1,
            plus_to_pro_today=1,
            subscription_expired_today=1,
            expiration_recovery_rate_30d=RateMetric(1, 1, 1.0),
        ),
        retention=RetentionMetrics(day_1=zero, day_7=zero, day_30=zero),
    )
