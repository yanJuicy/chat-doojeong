import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.work_items import create_work_item_router
from app.services.work_tracking.models import NaturalWorkEntryResponse, WorkItemDraft
from app.db.models import WorkItemStatus


class FakeExtractor:
    async def extract(self, request):  # noqa: ANN001
        return NaturalWorkEntryResponse(
            drafts=[
                WorkItemDraft(
                    title="주간보고서 설계",
                    status=WorkItemStatus.IN_PROGRESS,
                    confidence=0.9,
                    author=request.author,
                    department=request.department,
                )
            ]
        )


class WorkEntryApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        application = FastAPI()
        application.include_router(create_work_item_router(extractor=FakeExtractor()))
        cls.client = TestClient(application)

    def test_parse_returns_draft_that_requires_confirmation(self) -> None:
        response = self.client.post(
            "/api/work-entries/parse",
            json={
                "text": "주간보고서를 설계하고 있어",
                "reference_date": "2026-08-18",
                "author": "홍길동",
                "department": "개발팀",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["drafts"][0]["status"], "in_progress")
        self.assertEqual(payload["drafts"][0]["author"], "홍길동")

    def test_parse_rejects_unknown_fields(self) -> None:
        response = self.client.post(
            "/api/work-entries/parse",
            json={"text": "업무", "unexpected": True},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
