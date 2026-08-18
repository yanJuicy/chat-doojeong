"""채팅 보고서 명령에서 실제 보고서 도메인 모듈을 호출하는 핸들러."""

from __future__ import annotations

from ..services.work_tracking.repository import WorkItemRepository
from .common.commands import ReportCommand, ReportType
from .common.dispatcher import DispatchStatus, ReportDispatcher, ReportDispatchResult
from .weekly import WeeklyReportRequest, WeeklyReportService
from .weekly.documents import WeeklyDocumentRepository, WeeklyDocumentService


class WeeklyReportCommandHandler:
    def __init__(self, session_factory) -> None:  # noqa: ANN001
        self._session_factory = session_factory

    async def handle(self, command: ReportCommand) -> ReportDispatchResult:
        if command.period is None:
            return ReportDispatchResult(
                status=DispatchStatus.NEEDS_INPUT,
                report_type=ReportType.WEEKLY,
                message="주간보고서의 보고 기간이 필요합니다.",
                missing_fields=["period"],
            )
        request = WeeklyReportRequest(
            period_start=command.period.start_date,
            period_end=command.period.end_date,
            cutoff_date=command.period.cutoff_date,
        )
        async with self._session_factory() as session:
            report = await WeeklyReportService(WorkItemRepository(session)).generate(request)
            if not report.current_week and not report.next_week:
                return ReportDispatchResult(
                    status=DispatchStatus.NEEDS_INPUT,
                    report_type=ReportType.WEEKLY,
                    message="해당 기간에 저장된 업무가 없습니다. 업무를 먼저 입력해주세요.",
                    missing_fields=["work_items"],
                )
            document = await WeeklyDocumentService(WeeklyDocumentRepository(session)).generate(report)
        return ReportDispatchResult(
            status=DispatchStatus.GENERATED,
            report_type=ReportType.WEEKLY,
            message=(
                f"{report.period_start.isoformat()}부터 {report.period_end.isoformat()}까지의 "
                "주간보고서를 작성했습니다."
            ),
            report_id=document.report_id,
            download_url=f"/api/reports/generated/{document.report_id}/download",
        )


class ShipmentReportCommandHandler:
    async def handle(self, command: ReportCommand) -> ReportDispatchResult:
        return ReportDispatchResult(
            status=DispatchStatus.NEEDS_INPUT,
            report_type=ReportType.SHIPMENT,
            message=(
                f"{command.report_date.isoformat() if command.report_date else '지정일'} 출하보고서 모듈로 연결했습니다. "
                "생성하려면 고객사와 품목별 출하 계획·실적 데이터가 필요합니다."
            ),
            missing_fields=["customer", "plans", "actuals"],
        )


def create_report_dispatcher(session_factory) -> ReportDispatcher:  # noqa: ANN001
    return ReportDispatcher(
        {
            ReportType.WEEKLY: WeeklyReportCommandHandler(session_factory),
            ReportType.SHIPMENT: ShipmentReportCommandHandler(),
        }
    )
