import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.report_api.weekly_router import create_weekly_report_router
from app.reports.weekly import WeeklyReportDraft
from app.reports.weekly.documents import WeeklyDocument


def empty_report() -> WeeklyReportDraft:
    return WeeklyReportDraft(
        period_start=date(2026, 8, 17),
        period_end=date(2026, 8, 21),
        cutoff_date=date(2026, 8, 19),
        next_week_start=date(2026, 8, 24),
        next_week_end=date(2026, 8, 28),
        author="홍길동",
        department="개발팀",
        current_week=[],
        next_week=[],
        warnings=["등록된 금주 진행사항이 없습니다."],
        generated_at=datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc),
    )


class FakeSessionContext:
    async def __aenter__(self):  # noqa: ANN201
        return SimpleNamespace()

    async def __aexit__(self, *args):  # noqa: ANN002, ANN201
        return False


class FakeWeeklyReportService:
    def __init__(self, repository) -> None:  # noqa: ANN001
        self.repository = repository

    async def generate(self, body):  # noqa: ANN001, ANN201
        return empty_report().model_copy(update={"author": body.author, "department": body.department})


class FakeWeeklyDocumentService:
    def __init__(self, repository) -> None:  # noqa: ANN001
        self.repository = repository

    async def generate(self, body):  # noqa: ANN001, ANN201
        return WeeklyDocument(
            report_id="report-1",
            content=b"PK\x03\x04-test-docx",
            filename="weekly-report-2026-08-17-2026-08-21.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_path=Path("unused.docx"),
        )


class WeeklyReportApiTest(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(create_weekly_report_router(lambda: FakeSessionContext()))
        self.client = TestClient(app)

    def test_preview_endpoint_returns_structured_weekly_draft(self) -> None:
        with patch("app.report_api.weekly_router.WeeklyReportService", FakeWeeklyReportService):
            response = self.client.post(
                "/api/reports/weekly/generate",
                json={
                    "period_start": "2026-08-17",
                    "period_end": "2026-08-21",
                    "cutoff_date": "2026-08-19",
                    "author": "홍길동",
                    "department": "개발팀",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_type"], "WEEKLY")
        self.assertEqual(response.json()["author"], "홍길동")

    def test_document_endpoint_returns_attachment_and_report_id(self) -> None:
        with patch("app.report_api.weekly_router.WeeklyDocumentService", FakeWeeklyDocumentService):
            response = self.client.post(
                "/api/reports/weekly/documents",
                json=empty_report().model_dump(mode="json"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"PK\x03\x04-test-docx")
        self.assertEqual(response.headers["x-report-id"], "report-1")
        self.assertIn("attachment", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
