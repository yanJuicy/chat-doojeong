"""주간 업무보고서 집계 유스케이스."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from ...db.models import WorkItem
from .calculator import calculate_weekly_items
from .models import WeeklyReportDraft, WeeklyReportRequest
from .validator import validate_weekly_items


class WeeklyWorkItemSource(Protocol):
    async def list_for_weekly_report(self, request: WeeklyReportRequest) -> list[WorkItem]: ...


class WeeklyReportService:
    def __init__(self, work_item_source: WeeklyWorkItemSource) -> None:
        self._work_item_source = work_item_source

    async def generate(self, request: WeeklyReportRequest) -> WeeklyReportDraft:
        work_items = await self._work_item_source.list_for_weekly_report(request)
        current_week, next_week = calculate_weekly_items(request, work_items)
        warnings = validate_weekly_items(current_week, next_week)
        return WeeklyReportDraft(
            period_start=request.period_start,
            period_end=request.period_end,
            cutoff_date=request.cutoff_date,
            next_week_start=request.next_week_start,
            next_week_end=request.next_week_end,
            author=request.author,
            department=request.department,
            current_week=current_week,
            next_week=next_week,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        )
