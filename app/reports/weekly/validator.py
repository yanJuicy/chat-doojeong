"""집계된 주간보고서 초안의 품질 경고를 생성한다."""

from __future__ import annotations

from ...db.models import WorkItemStatus
from .models import WeeklyPlanItem, WeeklyProgressItem


def validate_weekly_items(
    current_week: list[WeeklyProgressItem],
    next_week: list[WeeklyPlanItem],
) -> list[str]:
    warnings: list[str] = []
    if not current_week:
        warnings.append("금주 진행사항으로 집계된 업무가 없습니다.")
    if not next_week:
        warnings.append("차주 진행 계획으로 집계된 업무가 없습니다.")

    for item in current_week:
        if item.status == WorkItemStatus.COMPLETED and not item.result and not item.activity_details:
            warnings.append(f"완료 업무 '{item.title}'에 결과 또는 활동 기록이 없습니다.")
        elif item.status == WorkItemStatus.IN_PROGRESS and not item.activity_details and not item.result:
            warnings.append(f"진행 중 업무 '{item.title}'에 진행 내용이 없습니다.")
    return warnings
