"""시각 검증용 주간보고서 DOCX 샘플을 생성한다."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from app.db.models import WorkItemStatus
from app.reports.weekly import WeeklyReportDraft
from app.reports.weekly.documents import WeeklyDocxRenderer
from app.reports.weekly.models import WeeklyPlanItem, WeeklyProgressItem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PROJECT_ROOT / "app" / "report_templates" / "weekly" / "default_v1.docx"
OUTPUT_PATH = PROJECT_ROOT / "reports" / "qa" / "weekly" / "sample_weekly_report.docx"


def build_sample() -> WeeklyReportDraft:
    return WeeklyReportDraft(
        period_start=date(2026, 8, 17),
        period_end=date(2026, 8, 21),
        cutoff_date=date(2026, 8, 19),
        next_week_start=date(2026, 8, 24),
        next_week_end=date(2026, 8, 28),
        author="홍길동",
        department="스마트팩토리 개발팀",
        current_week=[
            WeeklyProgressItem(
                work_item_id="1",
                title="주간보고서 자동 집계 및 미리보기 API 개발",
                category="백엔드",
                status=WorkItemStatus.COMPLETED,
                activity_details=["업무 기간별 집계 규칙 구현", "누락 항목 경고 검증 추가"],
                result="단위 테스트와 회귀 테스트 통과",
                completed_on=date(2026, 8, 19),
            ),
            WeeklyProgressItem(
                work_item_id="2",
                title="자연어 업무 메모 확인 화면 구현",
                category="프론트엔드",
                status=WorkItemStatus.IN_PROGRESS,
                activity_details=["추출 초안 편집 및 일괄 저장 흐름 연결"],
                result=None,
                completed_on=None,
            ),
        ],
        next_week=[
            WeeklyPlanItem(
                work_item_id="3",
                title="운영 검증",
                category="QA",
                plan="실제 사용자 업무 데이터로 생성 결과와 다운로드 이력을 점검",
                target_date=date(2026, 8, 25),
                carry_over=False,
                reasons=["NEXT_WEEK_DUE"],
            ),
            WeeklyPlanItem(
                work_item_id="4",
                title="출하보고서 데이터 연동",
                category="연동",
                plan="고객사 및 품목별 출하 계획·실적 데이터 소스 확정",
                target_date=date(2026, 8, 27),
                carry_over=True,
                reasons=["CARRY_OVER"],
            ),
        ],
        warnings=["프론트엔드 업무의 완료 결과를 제출 전에 확인하세요."],
        generated_at=datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc),
    )


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(WeeklyDocxRenderer().render(build_sample(), TEMPLATE_PATH))
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
