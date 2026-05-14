"""Profile / progress entrypoint."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.texts import (
    CALLBACK_PROFILE,
    PROFILE_DETAILS_HEADER,
    PROFILE_EMPTY_STATE_TEXT,
    PROFILE_NO_STRONG_THEMES_TEXT,
    PROFILE_NO_WEAK_THEMES_TEXT,
    PAYWALL_PROGRESS_TEXT,
    PROFILE_PROGRESS_TEMPLATE,
    PROFILE_RECOMMENDATION_HEADER,
    PROFILE_STRONG_THEMES_HEADER,
    PROFILE_TEXT,
    PROFILE_WEAK_THEMES_HEADER,
)
from app.bot.keyboards.main_menu import build_back_to_main_menu_button
from app.bot.keyboards.subscription import build_paywall_keyboard
from app.db.session import get_session as _get_session
from app.services.entitlements import EntitlementService, FEATURE_FULL_PROGRESS_MAP
from app.services.progress import ProgressService


router = Router(name="profile")

_progress_service = ProgressService()
_entitlement_service = EntitlementService()


def _session_factory():
    return _get_session()


def _format_progress_text(progress_records: list[object], *, recommendation_text: str | None = None) -> str:
    if not progress_records:
        return f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"

    strong_records = [record for record in progress_records if getattr(record, "topic_status", None) == "strong"]
    weak_records = [record for record in progress_records if getattr(record, "topic_status", None) == "weak"]
    lines = [
        PROFILE_TEXT,
        "",
        PROFILE_STRONG_THEMES_HEADER,
        *_summary_lines(strong_records, empty_text=PROFILE_NO_STRONG_THEMES_TEXT),
        "",
        PROFILE_WEAK_THEMES_HEADER,
        *_summary_lines(weak_records, empty_text=PROFILE_NO_WEAK_THEMES_TEXT),
        "",
        PROFILE_RECOMMENDATION_HEADER,
        recommendation_text or _fallback_recommendation(progress_records),
        "",
        PROFILE_DETAILS_HEADER,
    ]
    for record in progress_records:
        lines.append(_progress_detail_line(record))

    return "\n".join(lines)


async def _build_profile_text(db, telegram_user_id: int) -> str:
    try:
        progress_records = await _progress_service.get_user_summary(db, telegram_user_id)
        recommendation_builder = getattr(_progress_service, "build_recommendation_text", None)
        recommendation_text = recommendation_builder(progress_records) if recommendation_builder else None
        entitlement = await _entitlement_service.check_entitlement(
            db,
            telegram_user_id,
            feature=FEATURE_FULL_PROGRESS_MAP,
        )
    except Exception:
        progress_records = []
        recommendation_text = None
        entitlement = None
    if entitlement is not None and not entitlement.allowed:
        return _format_limited_progress_text(progress_records)
    return _format_progress_text(progress_records, recommendation_text=recommendation_text)


def _summary_lines(records: list[object], *, empty_text: str) -> list[str]:
    if not records:
        return [empty_text]
    return [
        f"{_status_icon(record)} {getattr(record, 'level', '—')} / {getattr(record, 'theme', '—') or '—'}"
        for record in records[:3]
    ]


def _progress_detail_line(record: object) -> str:
    return PROFILE_PROGRESS_TEMPLATE.format(
        status_icon=_status_icon(record),
        level=getattr(record, "level", "—"),
        theme=getattr(record, "theme", "—") or "—",
        correct=getattr(record, "total_correct", 0),
        answered=getattr(record, "total_answered", 0),
        accuracy=_format_score(getattr(record, "accuracy", 0)),
        coverage=_format_coverage(record),
        stability=_format_score(getattr(record, "stability_score", 0)),
        weakness=_format_score(getattr(record, "weakness_score", 0)),
    )


def _format_coverage(record: object) -> str:
    coverage_score = getattr(record, "coverage_score", None)
    if coverage_score is None or getattr(record, "coverage_status", None) == "unknown":
        return "offen"
    unique_seen = getattr(record, "unique_items_seen", 0) or 0
    available = getattr(record, "available_items_count", None)
    if available:
        return f"{unique_seen}/{available} Fragen ({_format_score(coverage_score)}%)"
    return f"{_format_score(coverage_score)}%"


def _format_score(value: object) -> str:
    text = f"{float(value or 0):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _status_icon(record: object) -> str:
    status = getattr(record, "topic_status", None)
    if status == "strong":
        return "✅"
    if status == "weak":
        return "⚠️"
    if status == "stable":
        return "🟢"
    return "📘"


def _fallback_recommendation(progress_records: list[object]) -> str:
    weak_records = [record for record in progress_records if getattr(record, "topic_status", None) == "weak"]
    if weak_records:
        record = weak_records[0]
        return f"Übe {getattr(record, 'theme', 'dein Thema')} auf Niveau {getattr(record, 'level', '')}."
    return "Mach mit einer kurzen Übung weiter, um deinen Fortschritt zu festigen."


def _format_limited_progress_text(progress_records: list[object]) -> str:
    if not progress_records:
        return f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"
    lines = [PROFILE_TEXT, ""]
    for record in progress_records[:3]:
        lines.append(
            f"📘 {getattr(record, 'level', '—')} / {getattr(record, 'theme', '—') or '—'}: "
            f"{getattr(record, 'total_correct', 0)}/{getattr(record, 'total_answered', 0)} korrekt."
        )
    lines.append("")
    lines.append(PAYWALL_PROGRESS_TEXT)
    return "\n".join(lines)


def _profile_keyboard(text: str):
    if PAYWALL_PROGRESS_TEXT in text:
        return build_paywall_keyboard()
    return build_back_to_main_menu_button()


@router.message(Command("profile"))
async def handle_profile_message(message: Message) -> None:
    user = message.from_user
    if user is None:
        await message.answer(PROFILE_EMPTY_STATE_TEXT, reply_markup=build_back_to_main_menu_button())
        return
    telegram_user_id = getattr(user, "id", None)
    if telegram_user_id is None:
        await message.answer(
            f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}",
            reply_markup=build_back_to_main_menu_button(),
        )
        return

    try:
        async with _session_factory() as db:
            text = await _build_profile_text(db, telegram_user_id)
    except Exception:
        text = f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"
    await message.answer(text, reply_markup=_profile_keyboard(text))


@router.callback_query(F.data == CALLBACK_PROFILE)
async def handle_profile_callback(callback_query: CallbackQuery) -> None:
    await callback_query.answer()
    if callback_query.message is not None:
        user = callback_query.from_user
        if user is None:
            await callback_query.message.answer(
                f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}",
                reply_markup=build_back_to_main_menu_button(),
            )
            return
        telegram_user_id = getattr(user, "id", None)
        if telegram_user_id is None:
            await callback_query.message.answer(
                f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}",
                reply_markup=build_back_to_main_menu_button(),
            )
            return

        try:
            async with _session_factory() as db:
                text = await _build_profile_text(db, telegram_user_id)
        except Exception:
            text = f"{PROFILE_TEXT}\n\n{PROFILE_EMPTY_STATE_TEXT}"
        await callback_query.message.answer(text, reply_markup=_profile_keyboard(text))
