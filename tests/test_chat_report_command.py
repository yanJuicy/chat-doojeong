import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.api_models import ChatRequest
from app.main import _run_chat_pipeline
from app.reports.common import DispatchStatus, ReportDispatchResult, ReportType


class FakeSession:
    def __init__(self) -> None:
        self.add = Mock()
        self.commit = AsyncMock()


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *args):  # noqa: ANN002, ANN201
        return False


class ChatReportCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_weekly_command_skips_rag_and_returns_download_action(self) -> None:
        session = FakeSession()
        dispatcher = SimpleNamespace(
            dispatch=AsyncMock(
                return_value=ReportDispatchResult(
                    status=DispatchStatus.GENERATED,
                    report_type=ReportType.WEEKLY,
                    message="주간보고서를 작성했습니다.",
                    report_id="report-1",
                    download_url="/api/reports/generated/report-1/download",
                )
            )
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

        with (
            patch("app.main.create_report_dispatcher", return_value=dispatcher),
            patch("app.main.async_session_factory", side_effect=lambda: FakeSessionContext(session)),
        ):
            events = [
                event
                async for event in _run_chat_pipeline(
                    request,
                    ChatRequest(question="이번 주 주간보고서 작성해줘"),
                )
            ]

        response = events[-1][1]
        self.assertEqual(response.action, "report_generated")
        self.assertEqual(response.report_type, "WEEKLY")
        self.assertEqual(response.report_id, "report-1")
        self.assertEqual(response.n_context_chunks, 0)
        dispatcher.dispatch.assert_awaited_once()
        session.add.assert_called_once()
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
