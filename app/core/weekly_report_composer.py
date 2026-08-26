"""
work_report_entries에 쌓인 항목을 모아 주간보고서 뷰로 조립한다.

원본 문서 경로에서 저장된 항목은 source_category(백엔드 개발/인프라 배포 등)가 붙어
있고, 이걸 그대로 보고서의 구분 행으로 살린다. 채팅으로 입력한 항목은 구분이 없어서
(source_category=None) 기본 구분 "사업관리"로 묶는다. 구분 행 순서는 실적/계획 항목이
DB에 쌓인 순서(created_at)를 따라 처음 등장한 순서 그대로 유지한다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from ..db.models import WeeklyReportEntry
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


_DEFAULT_CATEGORY = "사업관리"


@dataclass
class ReportItem:
    id: str
    content: str


@dataclass
class ReportPeriod:
    period_start: date
    period_end: date


@dataclass
class ReportCategoryRow:
    category: str
    current_items: list[ReportItem]
    next_items: list[ReportItem]


@dataclass
class WeeklyReportView:
    department: str
    current_period: ReportPeriod
    next_period: ReportPeriod
    rows: list[ReportCategoryRow]
    # 이 부서가 업로드한 원본 문서들이 쓰던 표현 형식(report_table_parser가 정규식으로 감지해
    # WeeklyReportEntry.source_format에 저장한 값의 다수결). 문서를 한 번도 안 올린 부서(채팅
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
            select(WeeklyReportEntry)
            .where(
                WeeklyReportEntry.department == department,
                WeeklyReportEntry.entry_type == "실적",
                WeeklyReportEntry.period_start == current_period[0],
                WeeklyReportEntry.period_end == current_period[1],
            )
            .order_by(WeeklyReportEntry.created_at)
        )
        next_result = await session.execute(
            select(WeeklyReportEntry)
            .where(
                WeeklyReportEntry.department == department,
                WeeklyReportEntry.entry_type == "계획",
                WeeklyReportEntry.period_start == next_period[0],
                WeeklyReportEntry.period_end == next_period[1],
            )
            .order_by(WeeklyReportEntry.created_at)
        )
        current_entries = current_result.scalars().all()
        next_entries = next_result.scalars().all()

        format_result = await session.execute(
            select(WeeklyReportEntry.source_format)
            .where(
                WeeklyReportEntry.department == department,
                WeeklyReportEntry.source == "document",
                WeeklyReportEntry.source_format.is_not(None),
            )
            .order_by(WeeklyReportEntry.created_at.desc())
            .limit(_FORMAT_SAMPLE_SIZE)
        )
        formats = [row[0] for row in format_result.all()]

    category_order: list[str] = []
    current_by_category: dict[str, list[ReportItem]] = {}
    next_by_category: dict[str, list[ReportItem]] = {}

    for entry in current_entries:
        category = entry.source_category or _DEFAULT_CATEGORY
        if category not in category_order:
            category_order.append(category)
        current_by_category.setdefault(category, []).append(ReportItem(id=entry.id, content=entry.content))

    for entry in next_entries:
        category = entry.source_category or _DEFAULT_CATEGORY
        if category not in category_order:
            category_order.append(category)
        next_by_category.setdefault(category, []).append(ReportItem(id=entry.id, content=entry.content))

    rows = [
        ReportCategoryRow(
            category=category,
            current_items=current_by_category.get(category, []),
            next_items=next_by_category.get(category, []),
        )
        for category in category_order
    ]
    if not rows:
        # 실적/계획 둘 다 없을 때도 빈 템플릿 한 행은 보여준다 (완전히 빈 표보다 낫다).
        rows = [ReportCategoryRow(category=_DEFAULT_CATEGORY, current_items=[], next_items=[])]

    return WeeklyReportView(
        department=department,
        current_period=ReportPeriod(period_start=current_period[0], period_end=current_period[1]),
        next_period=ReportPeriod(period_start=next_period[0], period_end=next_period[1]),
        rows=rows,
        source_format=Counter(formats).most_common(1)[0][0] if formats else None,
    )
