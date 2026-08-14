from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import main


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class WorkerOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_cycles_after_configured_document_batch(self) -> None:
        events: list[str] = []
        extraction_counts = iter([4, 4, 4, 0, 0])
        chunking_counts = iter([4, 4, 4, 0, 0])
        embedding_counts = iter([32, 0, 10, 0, 0])

        async def extract(*args, **kwargs) -> int:
            events.append("extract")
            return next(extraction_counts)

        async def chunk(*args, **kwargs) -> int:
            events.append("chunk")
            return next(chunking_counts)

        async def embed(*args, **kwargs) -> int:
            events.append("embed")
            return next(embedding_counts)

        async def unload() -> None:
            events.append("unload")

        app = SimpleNamespace(
            state=SimpleNamespace(
                gpu_lock=asyncio.Lock(),
                extractor_registry=object(),
                chunker=object(),
                embedding_provider=object(),
                llm_provider=SimpleNamespace(unload=unload),
                vector_store=object(),
            )
        )

        with (
            patch.object(main.settings, "worker_claim_batch_size", 4),
            patch.object(main.settings, "pipeline_round_document_limit", 8),
            patch.object(main, "async_session_factory", return_value=_SessionContext()),
            patch.object(main.extraction_worker, "process_pending_documents", side_effect=extract),
            patch.object(main.chunking_worker, "process_pending_documents", side_effect=chunk),
            patch.object(main.embedding_worker, "process_pending_chunks", side_effect=embed),
        ):
            await main._run_workers_in_background(app)

        self.assertEqual(events.count("unload"), 2)
        self.assertLess(events.index("embed"), events.index("extract", 2))
        self.assertEqual(events[-3:], ["extract", "chunk", "embed"])

    async def test_overlapping_requests_use_one_pipeline_at_a_time(self) -> None:
        active = 0
        maximum_active = 0
        extraction_counts = iter([0, 0])

        async def extract(*args, **kwargs) -> int:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            active -= 1
            return next(extraction_counts)

        app = SimpleNamespace(
            state=SimpleNamespace(
                gpu_lock=asyncio.Lock(),
                extractor_registry=object(),
                chunker=object(),
                embedding_provider=object(),
                llm_provider=SimpleNamespace(unload=AsyncMock()),
                vector_store=object(),
            )
        )

        with (
            patch.object(main, "async_session_factory", return_value=_SessionContext()),
            patch.object(main.extraction_worker, "process_pending_documents", side_effect=extract),
            patch.object(main.chunking_worker, "process_pending_documents", new=AsyncMock(return_value=0)),
            patch.object(main.embedding_worker, "process_pending_chunks", new=AsyncMock(return_value=0)),
        ):
            await asyncio.gather(
                main._run_workers_in_background(app),
                main._run_workers_in_background(app),
            )

        self.assertEqual(maximum_active, 1)


if __name__ == "__main__":
    unittest.main()
