"""업무 기록을 금주 진행사항과 차주 계획으로 결정적으로 분류한다."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ...db.models import WorkItem, WorkItemStatus
from .models import WeeklyPlanItem, WeeklyProgressItem, WeeklyReportRequest


_LOCAL_TIMEZONE = ZoneInfo("Asia/Seoul")


def _local_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(_LOCAL_TIMEZONE).date()


def _inside(value: date | None, start: date, end: date) -> bool:
    return value is not None and start <= value <= end


def calculate_weekly_items(
    request: WeeklyReportRequest,
    work_items: list[WorkItem],
) -> tuple[list[WeeklyProgressItem], list[WeeklyPlanItem]]:
    current_week: list[WeeklyProgressItem] = []
    next_week: list[WeeklyPlanItem] = []
    current_ids: set[str] = set()

    for item in work_items:
        activities = [
            activity
            for activity in item.activities
            if request.period_start <= activity.activity_date <= request.cutoff_date
        ]
        completed_on = _local_date(item.completed_at)
        created_on = _local_date(item.created_at)
        started_as_active = (
            _inside(item.start_date, request.period_start, request.cutoff_date)
            and item.status != WorkItemStatus.PLANNED
        )
        completed_this_week = _inside(completed_on, request.period_start, request.cutoff_date)
        created_as_active = (
            _inside(created_on, request.period_start, request.cutoff_date)
            and item.status in {WorkItemStatus.IN_PROGRESS, WorkItemStatus.ON_HOLD}
        )

        if activities or started_as_active or completed_this_week or created_as_active:
            current_ids.add(item.id)
            details = list(dict.fromkeys(activity.content.strip() for activity in activities if activity.content.strip()))
            current_week.append(
                WeeklyProgressItem(
                    work_item_id=item.id,
                    title=item.title,
                    category=item.category,
                    status=item.status,
                    activity_details=details,
                    result=item.result,
                    completed_on=completed_on if completed_this_week else None,
                )
            )

    for item in work_items:
        if item.status == WorkItemStatus.COMPLETED and not item.next_action:
            continue

        due_next_week = _inside(item.due_date, request.next_week_start, request.next_week_end)
        starts_next_week = _inside(item.start_date, request.next_week_start, request.next_week_end)
        has_next_action = item.id in current_ids and bool(item.next_action)
        carried = item.carry_over and item.status != WorkItemStatus.COMPLETED
        if not (due_next_week or starts_next_week or has_next_action or carried):
            continue

        reasons: list[str] = []
        if due_next_week:
            reasons.append("NEXT_WEEK_DUE")
        if starts_next_week:
            reasons.append("NEXT_WEEK_START")
        if has_next_action:
            reasons.append("NEXT_ACTION")
        if carried:
            reasons.append("CARRY_OVER")

        target_date = item.due_date if due_next_week else item.start_date if starts_next_week else None
        next_week.append(
            WeeklyPlanItem(
                work_item_id=item.id,
                title=item.title,
                category=item.category,
                plan=item.next_action or item.title,
                target_date=target_date,
                carry_over=carried,
                reasons=reasons,
            )
        )

    current_week.sort(key=lambda row: (row.category or "", row.title, row.work_item_id))
    next_week.sort(key=lambda row: (row.target_date or request.next_week_end, row.category or "", row.title))
    return current_week, next_week
