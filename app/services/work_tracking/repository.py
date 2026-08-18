"""SQLAlchemy 기반 업무 기록 저장소."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db.models import WorkActivity, WorkItem, WorkItemStatus

if TYPE_CHECKING:
    from ...reports.weekly.models import WeeklyReportRequest


_LOCAL_TIMEZONE = ZoneInfo("Asia/Seoul")


class WorkItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, item_id: str) -> WorkItem | None:
        result = await self._session.execute(
            select(WorkItem)
            .options(selectinload(WorkItem.activities))
            .where(WorkItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        status: WorkItemStatus | None = None,
        due_from: date | None = None,
        due_to: date | None = None,
    ) -> list[WorkItem]:
        statement = select(WorkItem).options(selectinload(WorkItem.activities))
        if status is not None:
            statement = statement.where(WorkItem.status == status)
        if due_from is not None:
            statement = statement.where(WorkItem.due_date >= due_from)
        if due_to is not None:
            statement = statement.where(WorkItem.due_date <= due_to)
        statement = statement.order_by(WorkItem.due_date.asc().nulls_last(), WorkItem.created_at.desc())
        result = await self._session.execute(statement)
        return list(result.scalars().unique().all())

    async def list_for_weekly_report(self, request: "WeeklyReportRequest") -> list[WorkItem]:
        """현재 주 실적 또는 다음 주 계획 후보만 관계 데이터와 함께 조회한다."""

        current_start = datetime.combine(request.period_start, time.min, _LOCAL_TIMEZONE).astimezone(timezone.utc)
        cutoff_exclusive = datetime.combine(
            request.cutoff_date + timedelta(days=1), time.min, _LOCAL_TIMEZONE
        ).astimezone(timezone.utc)
        activity_in_period = WorkItem.activities.any(
            and_(
                WorkActivity.activity_date >= request.period_start,
                WorkActivity.activity_date <= request.cutoff_date,
            )
        )
        statement = (
            select(WorkItem)
            .options(selectinload(WorkItem.activities))
            .where(
                or_(
                    and_(WorkItem.created_at >= current_start, WorkItem.created_at < cutoff_exclusive),
                    and_(WorkItem.completed_at >= current_start, WorkItem.completed_at < cutoff_exclusive),
                    and_(
                        WorkItem.start_date >= request.period_start,
                        WorkItem.start_date <= request.cutoff_date,
                    ),
                    activity_in_period,
                    and_(
                        WorkItem.due_date >= request.next_week_start,
                        WorkItem.due_date <= request.next_week_end,
                    ),
                    and_(
                        WorkItem.start_date >= request.next_week_start,
                        WorkItem.start_date <= request.next_week_end,
                    ),
                    WorkItem.carry_over.is_(True),
                )
            )
            .order_by(WorkItem.created_at.asc())
        )
        if request.author is not None:
            statement = statement.where(WorkItem.author == request.author)
        if request.department is not None:
            statement = statement.where(WorkItem.department == request.department)
        result = await self._session.execute(statement)
        return list(result.scalars().unique().all())

    def add(self, item: WorkItem) -> None:
        self._session.add(item)

    def add_activity(self, activity: WorkActivity) -> None:
        self._session.add(activity)

    async def flush(self) -> None:
        await self._session.flush()

    async def refresh(self, instance: object) -> None:
        await self._session.refresh(instance)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
