import unittest
from datetime import date

from app.reports.command_handlers import ShipmentReportCommandHandler
from app.reports.common import (
    DispatchStatus,
    ReportCommand,
    ReportDispatcher,
    ReportType,
    WeekPeriod,
)


class RecordingHandler:
    def __init__(self) -> None:
        self.command: ReportCommand | None = None

    async def handle(self, command: ReportCommand):  # noqa: ANN201
        from app.reports.common import ReportDispatchResult

        self.command = command
        return ReportDispatchResult(
            status=DispatchStatus.GENERATED,
            report_type=command.report_type,
            message="생성 완료",
            report_id="report-1",
            download_url="/download/report-1",
        )


class ReportDispatcherTest(unittest.IsolatedAsyncioTestCase):
    async def test_routes_weekly_command_to_registered_handler(self) -> None:
        handler = RecordingHandler()
        command = ReportCommand(
            report_type=ReportType.WEEKLY,
            period=WeekPeriod(
                start_date=date(2026, 8, 17),
                end_date=date(2026, 8, 21),
                cutoff_date=date(2026, 8, 19),
            ),
            original_text="주간보고서 작성해줘",
        )

        result = await ReportDispatcher({ReportType.WEEKLY: handler}).dispatch(command)

        self.assertIs(handler.command, command)
        self.assertEqual(result.status, DispatchStatus.GENERATED)
        self.assertEqual(result.download_url, "/download/report-1")

    async def test_shipment_command_is_routed_but_requests_source_data(self) -> None:
        command = ReportCommand(
            report_type=ReportType.SHIPMENT,
            report_date=date(2026, 8, 19),
            original_text="오늘 출하보고서 작성해줘",
        )

        result = await ShipmentReportCommandHandler().handle(command)

        self.assertEqual(result.status, DispatchStatus.NEEDS_INPUT)
        self.assertEqual(result.report_type, ReportType.SHIPMENT)
        self.assertEqual(result.missing_fields, ["customer", "plans", "actuals"])


if __name__ == "__main__":
    unittest.main()
