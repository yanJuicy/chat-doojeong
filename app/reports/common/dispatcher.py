"""구조화된 보고서 명령을 등록된 보고서 모듈로 전달한다."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .commands import ReportCommand, ReportType


class DispatchStatus(str, Enum):
    GENERATED = "GENERATED"
    NEEDS_INPUT = "NEEDS_INPUT"


class ReportDispatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: DispatchStatus
    report_type: ReportType
    message: str
    report_id: str | None = None
    download_url: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class ReportCommandHandler(Protocol):
    async def handle(self, command: ReportCommand) -> ReportDispatchResult: ...


class ReportDispatcher:
    def __init__(self, handlers: dict[ReportType, ReportCommandHandler]) -> None:
        self._handlers = handlers

    async def dispatch(self, command: ReportCommand) -> ReportDispatchResult:
        handler = self._handlers.get(command.report_type)
        if handler is None:
            return ReportDispatchResult(
                status=DispatchStatus.NEEDS_INPUT,
                report_type=command.report_type,
                message="지원하지 않는 보고서 종류입니다.",
            )
        return await handler.handle(command)
