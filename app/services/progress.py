from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.catalog.service import LocalCatalogNotConfiguredError, LocalCatalogQuizService
from app.catalog.selection import CatalogLevelDisabledError
from app.config import get_settings
from app.quiz_bank.errors import QuizBankError
from app.repositories.progress_history import ProgressHistoryRepository
from app.repositories.progress import ProgressRepository
from app.repositories.users import UserRepository
from app.services.progress_model import (
    TopicAnswerEvent,
    build_progress_recommendation,
    calculate_topic_scores,
    coverage_from_counts,
    recency_risk_score,
)
from app.services.user_identity import ResolvedUserId

RECENT_TOPIC_EVENTS_LIMIT = 200


@dataclass(frozen=True)
class _ProgressAnswerUpdate:
    user_id: int
    level: str
    theme: str | None
    is_correct: bool
    is_duplicate: bool
    session_id: int | None
    user_answer_id: int | None
    item_id: str | None
    theme_key: str | None
    available_items_count: int | None
    answered_at: datetime
    metadata_snapshot: dict[str, object] | None
    reason_code: str


@dataclass
class ProgressSummaryRow:
    """Display-only progress row for available topics without answers yet."""

    user_id: int
    level: str
    theme: str | None
    theme_key: str | None = None
    total_answered: int = 0
    total_correct: int = 0
    wrong_count: int = 0
    accuracy: Decimal = Decimal("0.00")
    unique_items_seen: int = 0
    available_items_count: int | None = None
    coverage_score: Decimal | None = Decimal("0.00")
    coverage_status: str = "known"
    stability_score: Decimal = Decimal("0.00")
    weakness_score: Decimal = Decimal("0.00")
    recency_score: Decimal = Decimal("100.00")
    topic_status: str = "new"
    last_answered_at: datetime | None = None


class _ProgressWriteService:
    """Runtime business logic for progress aggregation."""

    def __init__(
        self,
        *,
        user_repo: UserRepository | None = None,
        progress_repo: ProgressRepository | None = None,
        progress_history_repo: ProgressHistoryRepository | None = None,
        quiz_service: object | None = None,
    ) -> None:
        self._user_repo = user_repo or UserRepository()
        self._progress_repo = progress_repo or ProgressRepository()
        self._progress_history_repo = progress_history_repo or ProgressHistoryRepository()
        self._quiz_service = quiz_service

    async def record_answer_result(
        self,
        db,
        telegram_user_id: int | ResolvedUserId | None,
        *,
        level: str,
        theme: str | None,
        is_correct: bool,
        is_duplicate: bool,
        session_id: int | None = None,
        user_answer_id: int | None = None,
        item_id: str | None = None,
        theme_key: str | None = None,
        available_items_count: int | None = None,
        answered_at: datetime | None = None,
        metadata_snapshot: dict[str, object] | None = None,
        reason_code: str = "answer_accepted",
    ):
        now = answered_at or datetime.now(UTC)
        target_user_id = await self._resolve_user_id(
            db,
            identity=telegram_user_id,
        )
        answer_update = _ProgressAnswerUpdate(
            user_id=target_user_id,
            level=level,
            theme=theme,
            is_correct=is_correct,
            is_duplicate=is_duplicate,
            session_id=session_id,
            user_answer_id=user_answer_id,
            item_id=item_id,
            theme_key=theme_key,
            available_items_count=available_items_count,
            answered_at=now,
            metadata_snapshot=metadata_snapshot,
            reason_code=reason_code,
        )
        progress, totals_already_applied = await self._progress_for_answer(db, answer_update)
        await db.flush()

        if theme_key and not totals_already_applied:
            progress.theme_key = theme_key
        if is_duplicate:
            return progress
        return await self._record_new_answer(
            db,
            progress=progress,
            answer_update=answer_update,
            totals_already_applied=totals_already_applied,
        )

    async def _progress_for_answer(self, db, answer_update: _ProgressAnswerUpdate):
        progress = await self._progress_repo.get_by_user_level_theme(
            db,
            user_id=answer_update.user_id,
            level=answer_update.level,
            theme=answer_update.theme,
        )
        if progress is None:
            if answer_update.is_duplicate:
                progress = await self._progress_repo.create(
                    db,
                    user_id=answer_update.user_id,
                    level=answer_update.level,
                    theme=answer_update.theme,
                )
                return progress, False
            progress = await self._progress_repo.create_from_answer(
                db,
                user_id=answer_update.user_id,
                level=answer_update.level,
                theme=answer_update.theme,
                theme_key=answer_update.theme_key,
                is_correct=answer_update.is_correct,
                now=answer_update.answered_at,
            )
            return progress, True
        return progress, False

    async def _resolve_user_id(
        self,
        db,
        *,
        identity: int | ResolvedUserId | None,
    ) -> int:
        if isinstance(identity, ResolvedUserId):
            return identity.value
        if identity is None:
            raise ValueError("telegram_user_id is required when user_id is not provided")
        user = await self._user_repo.create_if_missing(db, identity)
        return int(user.id)

    async def _record_new_answer(
        self,
        db,
        *,
        progress,
        answer_update: _ProgressAnswerUpdate,
        totals_already_applied: bool = False,
    ):
        previous_status = progress.topic_status
        previous_scores = None if totals_already_applied else self._progress_history_repo.snapshot_scores(progress)
        if not totals_already_applied:
            await self._progress_repo.update_totals(
                db,
                progress,
                answered_delta=1,
                correct_delta=1 if answer_update.is_correct else 0,
                now=answer_update.answered_at,
            )
            await self._progress_repo.update_streak_if_supported(progress, is_correct=answer_update.is_correct)
        await self._apply_progress_model(
            db,
            progress=progress,
            answer_update=answer_update,
        )
        await self._progress_history_repo.record_answer_change(
            db,
            progress=progress,
            previous_status=previous_status,
            previous_scores=previous_scores,
            session_id=answer_update.session_id,
            user_answer_id=answer_update.user_answer_id,
            reason_code=answer_update.reason_code,
        )
        return progress

    async def _apply_progress_model(
        self,
        db,
        *,
        progress,
        answer_update: _ProgressAnswerUpdate,
    ) -> None:
        effective_available_items_count = _available_items_count(
            explicit_value=answer_update.available_items_count,
            metadata_snapshot=answer_update.metadata_snapshot,
            current_value=progress.available_items_count,
        )
        answer_events = await self._answer_events(db, progress, answer_update)
        mistake_signals = await self._progress_repo.get_topic_mistake_signals(
            db,
            user_id=answer_update.user_id,
            level=answer_update.level,
            theme=answer_update.theme,
        )
        unique_items_seen = await self._unique_items_seen(
            db,
            progress=progress,
            answer_update=answer_update,
            answer_events=answer_events,
        )
        scores = calculate_topic_scores(
            total_answered=int(progress.total_answered or 0),
            accuracy_score=progress.accuracy,
            unique_items_seen=unique_items_seen,
            available_items_count=effective_available_items_count,
            last_answered_at=progress.last_answered_at,
            answer_events=answer_events,
            mistake_signals=mistake_signals,
            now=answer_update.answered_at,
        )
        await self._progress_repo.apply_topic_scores(
            db,
            progress,
            scores=scores,
            unique_items_seen=unique_items_seen,
            available_items_count=effective_available_items_count,
            theme_key=answer_update.theme_key,
            now=answer_update.answered_at,
        )

    async def _answer_events(self, db, progress, answer_update: _ProgressAnswerUpdate) -> list[TopicAnswerEvent]:
        answer_events: list[TopicAnswerEvent] = []
        if int(progress.total_answered or 0) > 1:
            answer_events = await self._progress_repo.list_recent_topic_answer_events(
                db,
                user_id=answer_update.user_id,
                level=answer_update.level,
                theme=answer_update.theme,
                limit=RECENT_TOPIC_EVENTS_LIMIT,
            )
        return _with_current_event(
            answer_events,
            item_id=answer_update.item_id,
            is_correct=answer_update.is_correct,
            answered_at=answer_update.answered_at,
        )

    async def _unique_items_seen(
        self,
        db,
        *,
        progress,
        answer_update: _ProgressAnswerUpdate,
        answer_events: list[TopicAnswerEvent],
    ) -> int:
        current_value = int(getattr(progress, "unique_items_seen", 0) or 0)
        recent_unique = len({event.item_id for event in answer_events})
        if int(progress.total_answered or 0) <= 1:
            return max(1 if answer_update.item_id is not None else 0, recent_unique)
        if answer_update.item_id is None or answer_update.user_answer_id is None:
            return max(current_value, recent_unique)

        already_seen = await self._progress_repo.has_topic_item_answer(
            db,
            user_id=answer_update.user_id,
            level=answer_update.level,
            theme=answer_update.theme,
            item_id=answer_update.item_id,
            exclude_user_answer_id=answer_update.user_answer_id,
        )
        increment = 0 if already_seen else 1
        return max(current_value + increment, recent_unique)

class ProgressService(_ProgressWriteService):
    async def get_user_summary(self, db, telegram_user_id: int) -> list:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return []
        records = await self._progress_repo.get_user_summary(db, user_id=user.id)
        records = await self._with_available_topic_rows(db, user_id=user.id, records=records)
        _refresh_recency_for_display(records)
        return records

    async def get_level_theme_summary(
        self,
        db,
        telegram_user_id: int,
        *,
        level: str | None = None,
        theme: str | None = None,
    ) -> list:
        user = await self._user_repo.get_by_telegram_id(db, telegram_user_id)
        if user is None:
            return []
        records = await self._progress_repo.get_level_theme_summary(
            db,
            user_id=user.id,
            level=level,
            theme=theme,
        )
        if level is not None and theme is None:
            records = await self._with_available_topic_rows(
                db,
                user_id=user.id,
                records=records,
                levels=[level],
            )
        _refresh_recency_for_display(records)
        return records

    def build_recommendation_text(self, progress_records: list[object]) -> str:
        return build_progress_recommendation(progress_records).copy_de

    async def _with_available_topic_rows(
        self,
        db,
        *,
        user_id: int,
        records: list,
        levels: list[str] | None = None,
    ) -> list:
        quiz_service = self._get_quiz_service()
        if quiz_service is None:
            return records

        try:
            level_values = await self._catalog_levels(quiz_service, levels)
            catalog_rows = []
            for level in level_values:
                if isinstance(quiz_service, LocalCatalogQuizService):
                    themes = await quiz_service.get_themes(db, level=level)
                else:
                    themes = await quiz_service.get_themes(level=level)
                catalog_rows.extend((level, theme) for theme in themes.themes)
        except (CatalogLevelDisabledError, LocalCatalogNotConfiguredError, QuizBankError):
            return records

        by_key = {
            (getattr(record, "level", None), getattr(record, "theme", None)): record
            for record in records
        }
        for level, theme in catalog_rows:
            key = (level, theme.theme)
            existing = by_key.get(key)
            if existing is not None:
                _apply_catalog_counts(existing, theme)
                continue
            row = _empty_topic_row(user_id=user_id, level=level, theme=theme)
            by_key[key] = row
            records.append(row)
        return sorted(records, key=lambda item: (getattr(item, "level", ""), getattr(item, "theme", "") or ""))

    def _get_quiz_service(self):
        if self._quiz_service is not None:
            return self._quiz_service
        self._quiz_service = LocalCatalogQuizService()
        return self._quiz_service

    async def _catalog_levels(self, quiz_service: object, levels: list[str] | None) -> list[str]:
        if levels is not None:
            return levels
        if isinstance(quiz_service, LocalCatalogQuizService):
            return list(get_settings().enabled_cefr_levels)
        return [level.code for level in (await quiz_service.get_levels()).levels]


def _available_items_count(
    *,
    explicit_value: int | None,
    metadata_snapshot: dict[str, object] | None,
    current_value: int | None,
) -> int | None:
    if explicit_value is not None:
        return explicit_value
    if metadata_snapshot is not None:
        raw_value = metadata_snapshot.get("available_items_count")
        if isinstance(raw_value, int) and raw_value >= 0:
            return raw_value
    return current_value


def _with_current_event(
    answer_events: list[TopicAnswerEvent],
    *,
    item_id: str | None,
    is_correct: bool,
    answered_at: datetime,
) -> list[TopicAnswerEvent]:
    if not item_id:
        return answer_events
    if any(event.item_id == item_id and event.answered_at == answered_at for event in answer_events):
        return answer_events
    return [
        *answer_events,
        TopicAnswerEvent(item_id=item_id, is_correct=is_correct, answered_at=answered_at),
    ]


def _refresh_recency_for_display(progress_records: list[object]) -> None:
    for record in progress_records:
        if not hasattr(record, "last_answered_at") or not hasattr(record, "recency_score"):
            continue
        record.recency_score = recency_risk_score(getattr(record, "last_answered_at", None))


def _empty_topic_row(*, user_id: int, level: str, theme: object) -> ProgressSummaryRow:
    available_items_count = getattr(theme, "available_items_count", None)
    if not isinstance(available_items_count, int):
        available_items_count = None
    coverage_score = Decimal("0.00") if available_items_count is not None and available_items_count > 0 else None
    coverage_status = "known" if coverage_score is not None else "unknown"
    return ProgressSummaryRow(
        user_id=user_id,
        level=level,
        theme=getattr(theme, "theme", None),
        theme_key=getattr(theme, "theme_key", None),
        available_items_count=available_items_count,
        coverage_score=coverage_score,
        coverage_status=coverage_status,
    )


def _apply_catalog_counts(progress: object, theme: object) -> None:
    if getattr(progress, "theme_key", None) is None:
        setattr(progress, "theme_key", getattr(theme, "theme_key", None))
    available_items_count = getattr(theme, "available_items_count", None)
    if isinstance(available_items_count, int):
        setattr(progress, "available_items_count", available_items_count)
        coverage_score, coverage_status = coverage_from_counts(
            int(getattr(progress, "unique_items_seen", 0) or 0),
            available_items_count,
        )
        setattr(progress, "coverage_score", coverage_score)
        setattr(progress, "coverage_status", coverage_status)
