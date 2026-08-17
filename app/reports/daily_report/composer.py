"""검증된 입력값을 마크다운 보고서 하나로 조립한다."""
from __future__ import annotations

from .models import DailyReportRequest


def compose_title(request: DailyReportRequest) -> str:
    return f"{request.report_date.isoformat()} 업무일지 — {request.author}"


def compose_body(request: DailyReportRequest) -> str:
    lines: list[str] = [
        f"# {compose_title(request)}",
        "",
        "## 오늘 한 일",
        request.tasks_completed.strip(),
        "",
    ]

    if request.issues and request.issues.strip():
        lines += ["## 특이사항", request.issues.strip(), ""]

    if request.tomorrow_plan and request.tomorrow_plan.strip():
        lines += ["## 내일 계획", request.tomorrow_plan.strip(), ""]

    if request.reference_note and request.reference_note.strip():
        lines += ["## 참고자료", request.reference_note.strip(), ""]

    return "\n".join(lines).strip() + "\n"
