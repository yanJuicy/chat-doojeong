from __future__ import annotations

import unittest
from datetime import date

from app.core.report_table_parser import parse_report_table


class ParseReportTableFormatTests(unittest.TestCase):
    def _rows(self, cell_text: str) -> list[list[str]]:
        return [
            ["구분", "업무 실적\n(2026.08.17 ~ 2026.08.23)", "업무 계획\n(2026.08.24 ~ 2026.08.30)"],
            ["사업관리", cell_text, "계획 내용"],
        ]

    def test_bullet_dot_marker_detected(self) -> None:
        entries = parse_report_table(self._rows("• 항목1\n• 항목2"), "■ 부서명 : 개발팀")
        current_entries = [e for e in entries if e.entry_type == "실적"]
        self.assertEqual(len(current_entries), 2)
        for entry in current_entries:
            self.assertEqual(entry.source_format, "bullet:•")

    def test_dash_marker_detected(self) -> None:
        entries = parse_report_table(self._rows("- 항목1\n- 항목2"), "■ 부서명 : 개발팀")
        current_entries = [e for e in entries if e.entry_type == "실적"]
        self.assertEqual(len(current_entries), 2)
        for entry in current_entries:
            self.assertEqual(entry.source_format, "bullet:-")
        self.assertEqual(current_entries[0].content, "항목1")

    def test_prose_cell_has_no_marker(self) -> None:
        entries = parse_report_table(self._rows("항목1과 항목2를 함께 진행하였습니다."), "■ 부서명 : 개발팀")
        current_entries = [e for e in entries if e.entry_type == "실적"]
        self.assertEqual(len(current_entries), 1)
        self.assertEqual(current_entries[0].source_format, "prose")

    def test_empty_cell_returns_no_entries(self) -> None:
        entries = parse_report_table(self._rows(""), "■ 부서명 : 개발팀")
        current_entries = [e for e in entries if e.entry_type == "실적"]
        self.assertEqual(current_entries, [])


if __name__ == "__main__":
    unittest.main()
