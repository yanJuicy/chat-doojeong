"""
work_report_entries에 쌓인 항목을 모아 타겟 양식(구분 1개: "사업관리")에 맞는
주간보고서 뷰로 조립한다.

원본 문서 경로에서 저장된 항목은 source_category(사업/관리/시군특화 등)가 붙어 있지만,
타겟 양식은 구분이 하나뿐이라 여기서 그 태그를 무시하고 실적/계획으로만 나눠 합친다
(다대일 병합이라 정보 손실 없이 가능 — DB 모델 docstring 참고).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from ..db.models import WorkReportEntry
from ..db.session import async_session_factory


def week_of_month_label(monday: date) -> str:
    """
    "N월 M주차" 라벨을 계산한다. 실제 원본 문서 33주치에서 확인된 규칙: 그 주의
    월요일이 속한 달 기준으로, 그 달의 몇 번째 월요일인지로 정해진다(예: "1월
    4주차"(01.26~01.30) 다음이 "2월 1주차"(02.02~02.06) — 주의 끝(금요일)이 다음
    달로 넘어가도 라벨은 월요일 기준). 사람이 직접 지정할 필요 없이 그 주의
    월요일 날짜만 있으면 항상 정확히 계산된다.
    """
    first_of_month = monday.replace(day=1)
    first_monday = first_of_month + timedelta(days=(7 - first_of_month.weekday()) % 7)
    week_of_month = (monday - first_monday).days // 7 + 1
    return f"{monday.month}월 {week_of_month}주차"


@dataclass
class ReportItem:
    id: str
    content: str


@dataclass
class ReportPeriodBlock:
    period_start: date
    period_end: date
    items: list[ReportItem]


@dataclass
class WeeklyReportView:
    department: str
    current_week: ReportPeriodBlock
    next_week: ReportPeriodBlock
    # 이 부서가 업로드한 원본 문서들이 쓰던 표현 형식(report_table_parser가 정규식으로 감지해
    # WorkReportEntry.source_format에 저장한 값의 다수결). 문서를 한 번도 안 올린 부서(채팅
    # 입력만 있는 부서)는 None — 렌더러가 이때 기본 표현(•)으로 렌더링한다.
    source_format: str | None = None


_FORMAT_SAMPLE_SIZE = 30


async def compose_weekly_report(
    department: str,
    current_period: tuple[date, date],
    next_period: tuple[date, date],
) -> WeeklyReportView:
    async with async_session_factory() as session:
        current_result = await session.execute(
            select(WorkReportEntry)
            .where(
                WorkReportEntry.department == department,
                WorkReportEntry.entry_type == "실적",
                WorkReportEntry.period_start == current_period[0],
                WorkReportEntry.period_end == current_period[1],
            )
            .order_by(WorkReportEntry.created_at)
        )
        next_result = await session.execute(
            select(WorkReportEntry)
            .where(
                WorkReportEntry.department == department,
                WorkReportEntry.entry_type == "계획",
                WorkReportEntry.period_start == next_period[0],
                WorkReportEntry.period_end == next_period[1],
            )
            .order_by(WorkReportEntry.created_at)
        )
        current_entries = current_result.scalars().all()
        next_entries = next_result.scalars().all()

        format_result = await session.execute(
            select(WorkReportEntry.source_format)
            .where(
                WorkReportEntry.department == department,
                WorkReportEntry.source == "document",
                WorkReportEntry.source_format.is_not(None),
            )
            .order_by(WorkReportEntry.created_at.desc())
            .limit(_FORMAT_SAMPLE_SIZE)
        )
        formats = [row[0] for row in format_result.all()]

    return WeeklyReportView(
        department=department,
        current_week=ReportPeriodBlock(
            period_start=current_period[0],
            period_end=current_period[1],
            items=[ReportItem(id=e.id, content=e.content) for e in current_entries],
        ),
        next_week=ReportPeriodBlock(
            period_start=next_period[0],
            period_end=next_period[1],
            items=[ReportItem(id=e.id, content=e.content) for e in next_entries],
        ),
        source_format=Counter(formats).most_common(1)[0][0] if formats else None,
    )
