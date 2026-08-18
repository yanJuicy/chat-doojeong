"""자연어 보고서 명령을 제한된 내부 명령으로 변환한다."""

from __future__ import annotations

import re
from datetime import date, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReportType(str, Enum):
    WEEKLY = "WEEKLY"
    SHIPMENT = "SHIPMENT"


class ReportAction(str, Enum):
    GENERATE = "GENERATE"


class WeekPeriod(StrictModel):
    start_date: date
    end_date: date
    cutoff_date: date

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "WeekPeriod":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if not self.start_date <= self.cutoff_date <= self.end_date:
            raise ValueError("cutoff_date must be inside the report period")
        return self


class ReportCommand(StrictModel):
    action: ReportAction = ReportAction.GENERATE
    report_type: ReportType
    period: WeekPeriod | None = None
    report_date: date | None = None
    original_text: str


_ACTION_WORDS = ("작성해", "작성해줘", "생성해", "생성해줘", "만들어", "만들어줘", "출력해", "뽑아줘")
_INFORMATION_WORDS = ("작성법", "작성 방법", "어떻게 작성", "무엇", "뭐가", "예시")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def week_period(reference_date: date, offset_weeks: int = 0, cutoff_date: date | None = None) -> WeekPeriod:
    start = reference_date - timedelta(days=reference_date.weekday()) + timedelta(weeks=offset_weeks)
    end = start + timedelta(days=4)
    cutoff = cutoff_date or min(reference_date, end)
    if cutoff < start:
        cutoff = start
    return WeekPeriod(start_date=start, end_date=end, cutoff_date=cutoff)


def parse_report_command(text: str, reference_date: date | None = None) -> ReportCommand | None:
    """명확한 생성 요청만 보고서 명령으로 분류한다. 일반적인 질문은 ``None``을 반환한다."""

    normalized = " ".join(text.strip().split())
    compact = normalized.replace(" ", "")
    if not normalized or any(word in normalized for word in _INFORMATION_WORDS):
        return None
    if not any(word.replace(" ", "") in compact for word in _ACTION_WORDS):
        return None

    if "주간보고서" in compact:
        base = reference_date or date.today()
        dates = [date.fromisoformat(value) for value in _ISO_DATE.findall(normalized)]
        if len(dates) >= 2:
            cutoff = max(dates[0], min(base, dates[1]))
            period = WeekPeriod(start_date=dates[0], end_date=dates[1], cutoff_date=cutoff)
        else:
            offset = -1 if "지난주" in compact else 1 if "다음주" in compact else 0
            period = week_period(base, offset_weeks=offset)
        return ReportCommand(report_type=ReportType.WEEKLY, period=period, original_text=normalized)

    if "출하보고서" in compact:
        base = reference_date or date.today()
        dates = _ISO_DATE.findall(normalized)
        return ReportCommand(
            report_type=ReportType.SHIPMENT,
            report_date=date.fromisoformat(dates[0]) if dates else base,
            original_text=normalized,
        )

    return None
