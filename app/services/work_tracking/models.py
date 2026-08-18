"""업무 기록 API와 자연어 추출 결과의 데이터 계약."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...db.models import WorkItemStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrmModel(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)


class WorkItemCreate(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    author: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    status: WorkItemStatus = WorkItemStatus.PLANNED
    start_date: date | None = None
    due_date: date | None = None
    result: str | None = None
    next_action: str | None = None
    carry_over: bool = False

    @model_validator(mode="after")
    def date_range_is_valid(self) -> "WorkItemCreate":
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("due_date must be on or after start_date")
        return self


class WorkItemUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    author: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    status: WorkItemStatus | None = None
    start_date: date | None = None
    due_date: date | None = None
    result: str | None = None
    next_action: str | None = None
    carry_over: bool | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self) -> "WorkItemUpdate":
        for field in ("title", "status", "carry_over"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class WorkActivityCreate(StrictModel):
    activity_date: date = Field(default_factory=date.today)
    content: str = Field(min_length=1)
    status: WorkItemStatus | None = None


class WorkActivityRead(OrmModel):
    id: str
    work_item_id: str
    activity_date: date
    content: str
    status: WorkItemStatus | None
    created_at: datetime


class WorkItemRead(OrmModel):
    id: str
    title: str
    category: str | None
    author: str | None
    department: str | None
    status: WorkItemStatus
    start_date: date | None
    due_date: date | None
    completed_at: datetime | None
    result: str | None
    next_action: str | None
    carry_over: bool
    created_at: datetime
    updated_at: datetime
    activities: list[WorkActivityRead] = Field(default_factory=list)


class WorkItemBulkCreate(StrictModel):
    items: list[WorkItemCreate] = Field(min_length=1, max_length=100)


class WorkItemList(StrictModel):
    items: list[WorkItemRead]
    total: int = Field(ge=0)


class NaturalWorkEntryRequest(StrictModel):
    text: str = Field(min_length=1, max_length=10000)
    reference_date: date = Field(default_factory=date.today)
    author: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)


class WorkItemDraft(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=100)
    author: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    status: WorkItemStatus
    start_date: date | None = None
    due_date: date | None = None
    result: str | None = None
    next_action: str | None = None
    carry_over: bool = False
    confidence: float = Field(ge=0, le=1)


class NaturalWorkEntryResponse(StrictModel):
    drafts: list[WorkItemDraft]
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
