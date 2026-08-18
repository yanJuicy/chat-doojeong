"""주간 업무보고서 집계의 입력·출력 계약."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...db.models import WorkItemStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WeeklyReportRequest(StrictModel):
    period_start: date
    period_end: date
    cutoff_date: date
    author: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_business_week(self) -> "WeeklyReportRequest":
        if self.period_start.weekday() != 0:
            raise ValueError("period_start must be Monday")
        if self.period_end != self.period_start + timedelta(days=4):
            raise ValueError("period_end must be Friday of the same report week")
        if not self.period_start <= self.cutoff_date <= self.period_end:
            raise ValueError("cutoff_date must be inside the report period")
        return self

    @property
    def next_week_start(self) -> date:
        return self.period_start + timedelta(days=7)

    @property
    def next_week_end(self) -> date:
        return self.period_end + timedelta(days=7)


class WeeklyProgressItem(StrictModel):
    work_item_id: str
    title: str
    category: str | None
    status: WorkItemStatus
    activity_details: list[str] = Field(default_factory=list)
    result: str | None
    completed_on: date | None


class WeeklyPlanItem(StrictModel):
    work_item_id: str
    title: str
    category: str | None
    plan: str
    target_date: date | None
    carry_over: bool
    reasons: list[str] = Field(default_factory=list)


class WeeklyReportDraft(StrictModel):
    report_type: str = "WEEKLY"
    status: str = "DRAFT"
    period_start: date
    period_end: date
    cutoff_date: date
    next_week_start: date
    next_week_end: date
    author: str | None
    department: str | None
    current_week: list[WeeklyProgressItem]
    next_week: list[WeeklyPlanItem]
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime
