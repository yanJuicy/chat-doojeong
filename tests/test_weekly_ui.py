import unittest
from pathlib import Path


INDEX_HTML = Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"


class WeeklyUiContractTest(unittest.TestCase):
    def test_exposes_work_capture_preview_edit_and_docx_download_flow(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")

        for contract in (
            'id="workNaturalText"',
            'id="weeklyPreview"',
            "function parseWorkEntry()",
            "function confirmWorkDrafts()",
            "function generateWeeklyPreview()",
            "function syncWeeklyPreviewFromDom()",
            "function downloadWeeklyDocx()",
            "in_progress: '진행 중'",
            "function workStatusOptions(selectedStatus)",
            "'/api/work-entries/parse'",
            "'/api/work-items/bulk'",
            "'/api/reports/weekly/generate'",
            "'/api/reports/weekly/documents'",
        ):
            self.assertIn(contract, html)


if __name__ == "__main__":
    unittest.main()
