import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError

from app.db.models import WorkActivity, WorkItem, WorkItemStatus
from app.reports.weekly import WeeklyReportRequest, WeeklyReportService
from app.reports.weekly.calculator import calculate_weekly_items


def make_item(
    item_id: str,
    title: str,
    *,
    status: WorkItemStatus = WorkItemStatus.PLANNED,
    created_on: date = date(2026, 8, 1),
    start_date: date | None = None,
    due_date: date | None = None,
    completed_on: date | None = None,
    result: str | None = None,
    next_action: str | None = None,
    carry_over: bool = False,
    activity_rows: list[tuple[date, str]] | None = None,
) -> WorkItem:
    item = WorkItem(
        id=item_id,
        title=title,
        category="개발",
        status=status,
        start_date=start_date,
        due_date=due_date,
        completed_at=(
            datetime.combine(completed_on, datetime.min.time(), timezone.utc)
            if completed_on
            else None
        ),
        result=result,
        next_action=next_action,
        carry_over=carry_over,
    )
    item.created_at = datetime.combine(created_on, datetime.min.time(), timezone.utc)
    item.updated_at = item.created_at
    item.activities = [
        WorkActivity(
            id=f"{item_id}-activity-{index}",
            work_item_id=item_id,
            activity_date=activity_date,
            content=content,
            status=status,
            created_at=datetime.combine(activity_date, datetime.min.time(), timezone.utc),
        )
        for index, (activity_date, content) in enumerate(activity_rows or [], start=1)
    ]
    return item


def request() -> WeeklyReportRequest:
    return WeeklyReportRequest(
        period_start=date(2026, 8, 17),
        period_end=date(2026, 8, 21),
        cutoff_date=date(2026, 8, 19),
        author="홍길동",
        department="개발팀",
    )


class FakeWeeklySource:
    def __init__(self, items: list[WorkItem]) -> None:
        self.items = items
        self.received_request: WeeklyReportRequest | None = None

    async def list_for_weekly_report(self, report_request: WeeklyReportRequest) -> list[WorkItem]:
        self.received_request = report_request
        return self.items


class WeeklyReportRequestTest(unittest.TestCase):
    def test_requires_monday_to_friday_period(self) -> None:
        with self.assertRaises(ValidationError):
            WeeklyReportRequest(
                period_start=date(2026, 8, 18),
                period_end=date(2026, 8, 21),
                cutoff_date=date(2026, 8, 19),
            )

    def test_requires_cutoff_inside_period(self) -> None:
        with self.assertRaises(ValidationError):
            WeeklyReportRequest(
                period_start=date(2026, 8, 17),
                period_end=date(2026, 8, 21),
                cutoff_date=date(2026, 8, 22),
            )


class WeeklyCalculatorTest(unittest.TestCase):
    def test_classifies_current_progress_and_next_plans(self) -> None:
        items = [
            make_item(
                "done",
                "출하보고서 API 개발",
                status=WorkItemStatus.COMPLETED,
                completed_on=date(2026, 8, 18),
                result="API와 테스트 완료",
                next_action="배포 환경 검증",
                activity_rows=[(date(2026, 8, 18), "다운로드 테스트 완료")],
            ),
            make_item(
                "active",
                "주간보고서 설계",
                status=WorkItemStatus.IN_PROGRESS,
                created_on=date(2026, 8, 17),
            ),
            make_item(
                "planned",
                "주간보고서 화면 개발",
                status=WorkItemStatus.PLANNED,
                start_date=date(2026, 8, 24),
                due_date=date(2026, 8, 26),
            ),
            make_item(
                "carry",
                "검색 정확도 개선",
                status=WorkItemStatus.IN_PROGRESS,
                carry_over=True,
            ),
            make_item(
                "future-activity",
                "기준일 이후 업무",
                status=WorkItemStatus.IN_PROGRESS,
                activity_rows=[(date(2026, 8, 20), "목요일 진행")],
            ),
        ]

        current, following = calculate_weekly_items(request(), items)

        self.assertEqual({row.work_item_id for row in current}, {"done", "active"})
        done = next(row for row in current if row.work_item_id == "done")
        self.assertEqual(done.activity_details, ["다운로드 테스트 완료"])
        self.assertEqual(done.completed_on, date(2026, 8, 18))

        self.assertEqual({row.work_item_id for row in following}, {"done", "planned", "carry"})
        planned = next(row for row in following if row.work_item_id == "planned")
        self.assertEqual(planned.target_date, date(2026, 8, 26))
        self.assertIn("NEXT_WEEK_DUE", planned.reasons)
        carry = next(row for row in following if row.work_item_id == "carry")
        self.assertTrue(carry.carry_over)
        done_plan = next(row for row in following if row.work_item_id == "done")
        self.assertEqual(done_plan.plan, "배포 환경 검증")

    def test_planned_item_starting_this_week_is_not_reported_as_progress(self) -> None:
        item = make_item(
            "planned",
            "아직 시작하지 않은 업무",
            status=WorkItemStatus.PLANNED,
            start_date=date(2026, 8, 18),
        )

        current, following = calculate_weekly_items(request(), [item])

        self.assertEqual(current, [])
        self.assertEqual(following, [])


class WeeklyReportServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_generates_draft_with_quality_warnings(self) -> None:
        source = FakeWeeklySource(
            [
                make_item(
                    "active",
                    "주간보고서 설계",
                    status=WorkItemStatus.IN_PROGRESS,
                    created_on=date(2026, 8, 17),
                )
            ]
        )

        report = await WeeklyReportService(source).generate(request())

        self.assertEqual(report.report_type, "WEEKLY")
        self.assertEqual(report.status, "DRAFT")
        self.assertEqual(report.next_week_start, date(2026, 8, 24))
        self.assertTrue(any("진행 내용" in warning for warning in report.warnings))
        self.assertTrue(any("차주 진행 계획" in warning for warning in report.warnings))
        self.assertIsNotNone(source.received_request)

    async def test_empty_data_returns_both_empty_section_warnings(self) -> None:
        report = await WeeklyReportService(FakeWeeklySource([])).generate(request())

        self.assertEqual(report.current_week, [])
        self.assertEqual(report.next_week, [])
        self.assertEqual(len(report.warnings), 2)


if __name__ == "__main__":
    unittest.main()
