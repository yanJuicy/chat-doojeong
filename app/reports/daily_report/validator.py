"""일일 업무 보고서 입력값 검증."""
from __future__ import annotations

from .models import DailyReportRequest, ValidationIssue

_MIN_TASKS_LENGTH = 5  # "오늘 한 일"이 최소한의 내용을 담고 있는지(빈 칸/한 글자 방지)


def validate_request(request: DailyReportRequest) -> list[ValidationIssue]:
    """필수 항목이 비어있거나 너무 부실하면 이슈 목록을 반환한다 (비어있으면 통과)."""
    issues: list[ValidationIssue] = []

    if not request.author.strip():
        issues.append(ValidationIssue(field="author", message="작성자를 입력해 주세요."))

    if len(request.tasks_completed.strip()) < _MIN_TASKS_LENGTH:
        issues.append(
            ValidationIssue(
                field="tasks_completed",
                message=f"오늘 한 일을 좀 더 구체적으로 적어 주세요 (최소 {_MIN_TASKS_LENGTH}자).",
            )
        )

    return issues
