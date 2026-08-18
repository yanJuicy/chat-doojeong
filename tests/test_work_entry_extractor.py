import unittest
from datetime import date

from app.core.llm_provider import BaseLLMProvider
from app.db.models import WorkItemStatus
from app.services.work_tracking.extractor import NaturalWorkEntryExtractor, WorkEntryExtractionError
from app.services.work_tracking.models import NaturalWorkEntryRequest


class FakeLLMProvider(BaseLLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt = ""
        self.last_system_prompt = ""

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt or ""
        return self.response

    async def generate_stream(self, prompt: str, system_prompt: str | None = None):
        if False:
            yield ""


class NaturalWorkEntryExtractorTest(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_validated_drafts_without_saving(self) -> None:
        provider = FakeLLMProvider(
            """```json
{"items":[{"title":"출하보고서 API 개발","category":"개발","status":"completed",
"start_date":null,"due_date":null,"result":"API 개발 완료","next_action":null,
"carry_over":false,"confidence":0.96}],"warnings":[]}
```"""
        )
        extractor = NaturalWorkEntryExtractor(provider)

        result = await extractor.extract(
            NaturalWorkEntryRequest(
                text="오늘 출하보고서 API 개발을 완료했어.",
                reference_date=date(2026, 8, 18),
                author="홍길동",
                department="개발팀",
            )
        )

        self.assertTrue(result.requires_confirmation)
        self.assertEqual(len(result.drafts), 1)
        self.assertEqual(result.drafts[0].status, WorkItemStatus.COMPLETED)
        self.assertEqual(result.drafts[0].author, "홍길동")
        self.assertEqual(result.drafts[0].department, "개발팀")
        self.assertIn("2026-08-18", provider.last_prompt)
        self.assertIn("추측하지 마세요", provider.last_system_prompt)

    async def test_rejects_unknown_status(self) -> None:
        provider = FakeLLMProvider(
            '{"items":[{"title":"업무","status":"done","confidence":0.8}],"warnings":[]}'
        )

        with self.assertRaises(WorkEntryExtractionError):
            await NaturalWorkEntryExtractor(provider).extract(
                NaturalWorkEntryRequest(text="업무 끝", reference_date=date(2026, 8, 18))
            )

    async def test_empty_result_returns_warning(self) -> None:
        provider = FakeLLMProvider('{"items":[],"warnings":[]}')

        result = await NaturalWorkEntryExtractor(provider).extract(
            NaturalWorkEntryRequest(text="특별한 내용 없음", reference_date=date(2026, 8, 18))
        )

        self.assertEqual(result.drafts, [])
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
