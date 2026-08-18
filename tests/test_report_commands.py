import unittest
from datetime import date

from app.reports.common import ReportType, parse_report_command


class ReportCommandTest(unittest.TestCase):
    def test_current_week_command_resolves_monday_to_friday_and_cutoff(self) -> None:
        command = parse_report_command("이번 주 주간 보고서 작성해줘", date(2026, 8, 19))

        self.assertIsNotNone(command)
        assert command is not None and command.period is not None
        self.assertEqual(command.report_type, ReportType.WEEKLY)
        self.assertEqual(command.period.start_date, date(2026, 8, 17))
        self.assertEqual(command.period.end_date, date(2026, 8, 21))
        self.assertEqual(command.period.cutoff_date, date(2026, 8, 19))

    def test_previous_week_command_uses_previous_business_week(self) -> None:
        command = parse_report_command("지난주 주간보고서 만들어줘", date(2026, 8, 19))

        assert command is not None and command.period is not None
        self.assertEqual(command.period.start_date, date(2026, 8, 10))
        self.assertEqual(command.period.end_date, date(2026, 8, 14))
        self.assertEqual(command.period.cutoff_date, date(2026, 8, 14))

    def test_information_question_is_not_treated_as_generation(self) -> None:
        self.assertIsNone(parse_report_command("주간보고서 작성 방법을 알려줘", date(2026, 8, 19)))

    def test_shipment_command_uses_explicit_date(self) -> None:
        command = parse_report_command("2026-08-14 출하보고서 생성해줘", date(2026, 8, 19))

        assert command is not None
        self.assertEqual(command.report_type, ReportType.SHIPMENT)
        self.assertEqual(command.report_date, date(2026, 8, 14))

    def test_future_explicit_week_clamps_cutoff_to_period_start(self) -> None:
        command = parse_report_command(
            "2026-08-24 2026-08-28 주간보고서 작성해줘",
            date(2026, 8, 19),
        )

        assert command is not None and command.period is not None
        self.assertEqual(command.period.cutoff_date, date(2026, 8, 24))


if __name__ == "__main__":
    unittest.main()
