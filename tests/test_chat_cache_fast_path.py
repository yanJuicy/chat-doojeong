from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.api_models import ChatRequest
from app.main import _run_chat_pipeline


class ExactCacheFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_hit_skips_question_embedding(self) -> None:
        embedding_provider = SimpleNamespace(embed_hybrid=AsyncMock())
        cached_entry = SimpleNamespace(
            answer="cached answer",
            n_context_chunks=1,
            images=[],
            sources=[],
            intent_scores=[],
        )
        question_cache = SimpleNamespace(
            get_exact=Mock(return_value=SimpleNamespace(entry=cached_entry))
        )
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    gpu_lock=asyncio.Lock(),
                    embedding_provider=embedding_provider,
                    vector_store=object(),
                    reranker=object(),
                    llm_provider=object(),
                    intent_classifier=object(),
                    question_cache=question_cache,
                )
            )
        )

        events = [
            event
            async for event in _run_chat_pipeline(
                request,
                ChatRequest(question="같은 질문입니다"),
            )
        ]

        embedding_provider.embed_hybrid.assert_not_awaited()
        self.assertEqual("cached answer", events[-1][1].answer)
        self.assertTrue(events[-1][1].cache_hit)


if __name__ == "__main__":
    unittest.main()
