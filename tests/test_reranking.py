from __future__ import annotations

import asyncio
import inspect
import unittest

from app.core.bge_reranker import BgeRerankerV2
from app.core.lexical_scoring import keyword_overlap_score, match_query_terms, query_terms
from app.core.lightweight_reranker import lightweight_rerank
from app.core.reranker import BaseReranker
from app.core.retrieval_merge import merge_global_and_labeled_candidates
from app.core.vector_store import SearchResult


def _result(chunk_id: str, text: str, score: float, document_id: str = "doc") -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        text=text,
        score=score,
        metadata={"document_id": document_id},
    )


class LexicalScoringTests(unittest.TestCase):
    def test_match_query_terms_ignores_spacing(self) -> None:
        terms = query_terms("서빙로봇의 주행 속도")

        self.assertEqual(match_query_terms(terms, "서빙 로봇 최대 주행 속도"), {"서빙로봇", "주행", "속도"})

    def test_lightweight_reranker_prefers_keyword_and_document_match(self) -> None:
        candidates = [
            _result("semantic", "일반 제품 소개", 0.9, "other"),
            _result("exact", "RB5-850 최대 주행 속도는 1.2 m/s", 0.1, "preferred"),
        ]

        reranked = lightweight_rerank(
            "RB5-850의 최대 주행 속도는?",
            candidates,
            preferred_document_ids={"preferred"},
        )

        self.assertEqual(reranked[0].chunk_id, "exact")

    def test_merge_protects_lexically_matching_candidate(self) -> None:
        global_results = [
            _result(f"global-{index}", "일반 설명", 1.0 - index / 100)
            for index in range(6)
        ]
        exact = _result("exact", "RB5-850 최대 주행 속도", 0.01)

        merged = merge_global_and_labeled_candidates(
            global_results,
            [exact],
            max_count=4,
            query="RB5-850의 최대 주행 속도는?",
        )

        self.assertIn("exact", [result.chunk_id for result in merged])


class RerankerInterfaceTests(unittest.TestCase):
    def test_base_interface_accepts_preferred_document_ids(self) -> None:
        parameter = inspect.signature(BaseReranker.rerank).parameters["preferred_document_ids"]

        self.assertEqual(parameter.default, ())


class _CudaOutOfMemory(RuntimeError):
    pass


class _FakeCuda:
    OutOfMemoryError = _CudaOutOfMemory

    def __init__(self) -> None:
        self.empty_cache_called = False

    def empty_cache(self) -> None:
        self.empty_cache_called = True


class _FakeTorch:
    def __init__(self) -> None:
        self.cuda = _FakeCuda()


class _OomModel:
    def compute_score(self, pairs: list[list[str]], normalize: bool) -> list[float]:
        raise _CudaOutOfMemory("CUDA out of memory")


class _BrokenModel:
    def compute_score(self, pairs: list[list[str]], normalize: bool) -> list[float]:
        raise RuntimeError("unexpected model failure")


def _reranker_with_model(model: object) -> BgeRerankerV2:
    reranker = BgeRerankerV2.__new__(BgeRerankerV2)
    reranker._torch = _FakeTorch()
    reranker._rerank_lock = asyncio.Lock()
    reranker._use_cuda = True
    reranker._model = model
    return reranker


class BgeRerankerFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_cuda_oom_disables_model_and_falls_back(self) -> None:
        reranker = _reranker_with_model(_OomModel())
        candidates = [
            _result("semantic", "일반 제품 소개", 0.9, "other"),
            _result("exact", "RB5-850 최대 주행 속도는 1.2 m/s", 0.1, "preferred"),
        ]

        reranked = await reranker.rerank(
            "RB5-850의 최대 주행 속도는?",
            candidates,
            top_k=1,
            preferred_document_ids={"preferred"},
        )

        self.assertEqual(reranked[0].chunk_id, "exact")
        self.assertFalse(reranker.using_cuda)
        self.assertIsNone(reranker._model)
        self.assertTrue(reranker._torch.cuda.empty_cache_called)

    async def test_non_oom_runtime_error_is_not_hidden(self) -> None:
        reranker = _reranker_with_model(_BrokenModel())

        with self.assertRaisesRegex(RuntimeError, "unexpected model failure"):
            await reranker.rerank("질문", [_result("one", "본문", 0.5)])

        self.assertTrue(reranker.using_cuda)
        self.assertIsNotNone(reranker._model)


if __name__ == "__main__":
    unittest.main()
