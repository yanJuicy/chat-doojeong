"""일일 업무 보고서 데이터 모델.

이유빈 님의 app/reports/shipment 구조를 그대로 따른다:
  models(형식) -> validator(검증) -> composer(조립) -> service(지휘) -> router(API)
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"


class DailyReportRequest(BaseModel):
    """사람이 직접 입력하는 보고서 폼. 참고자료는 여기 필드로 복사/붙여넣기 해서 채운다."""

    report_date: date
    author: str
    tasks_completed: str  # 오늘 한 일 (여러 줄 자유 서술)
    issues: str | None = None  # 특이사항/이슈 (선택)
    tomorrow_plan: str | None = None  # 내일 계획 (선택)
    reference_note: str | None = None  # 참고자료에서 붙여넣은 메모 (선택, 보고서 하단에 그대로 실림)


class ValidationIssue(BaseModel):
    field: str
    message: str


class DailyReportResult(BaseModel):
    status: ValidationStatus
    title: str | None = None
    body_markdown: str | None = None  # 최종 조립된 보고서 (마크다운)
    issues: list[ValidationIssue] = Field(default_factory=list)


class ReferenceSource(str, Enum):
    DOCUMENT = "document"
    CHAT_LOG = "chat_log"


class ReferenceItem(BaseModel):
    """참고자료 패널에 뿌려줄 항목 하나 — 화면에서 그대로 선택해 복사/붙여넣기 하는 대상."""

    source: ReferenceSource
    title: str  # 문서면 파일명, 채팅이면 질문 원문
    snippet: str  # 실제로 복사해서 쓸 본문
    reference_id: str  # document_id 또는 chat_log id
    created_at: str | None = None


class ReferenceSearchResult(BaseModel):
    query: str
    items: list[ReferenceItem] = Field(default_factory=list)
