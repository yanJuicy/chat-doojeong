from __future__ import annotations

import unittest

from app.core.retrieval_trace import (
    STAGE_BOOSTED,
    STAGE_FINAL,
    STAGE_FLOOR,
    STAGE_GLOBAL,
    STAGE_LABELED,
    STAGE_MERGED,
    STAGE_READY,
    STAGE_RERANKED,
    expected_stage_ranks,
    find_drop_stage,
    snapshot_candidates,
)
from app.core.vector_store import SearchResult


def _result(chunk_id: str, document_id: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        text=f"text-{chunk_id}",
        score=score,
        metadata={"document_id": document_id},
    )


def _snapshot(stage: str, document_ids: list[str]) -> dict:
    return snapshot_candidates(
        stage,
        [_result(f"{stage}-{index}", document_id, 1.0 - index / 10) for index, document_id in enumerate(document_ids)],
    )


class RetrievalTraceTests(unittest.TestCase):
    def test_snapshot_copies_rank_identity_and_score(self) -> None:
        result = _result("chunk-1", "doc-1", 0.75)
        snapshot = snapshot_candidates(STAGE_GLOBAL, [result])
        result.score = 0.1

        self.assertEqual(
            snapshot["candidates"][0],
            {"rank": 1, "document_id": "doc-1", "chunk_id": "chunk-1", "score": 0.75},
        )

    def test_expected_stage_ranks_reports_each_snapshot(self) -> None:
        trace = [
            _snapshot(STAGE_GLOBAL, ["other", "expected"]),
            _snapshot(STAGE_FINAL, ["expected"]),
        ]

        self.assertEqual(
            expected_stage_ranks(trace, {"expected"}),
            {STAGE_GLOBAL: 2, STAGE_FINAL: 1},
        )

    def test_drop_stage_is_floor_when_answer_survives_until_floor(self) -> None:
        trace = [
            _snapshot(STAGE_GLOBAL, ["expected"]),
            _snapshot(STAGE_LABELED, []),
            _snapshot(STAGE_MERGED, ["expected"]),
            _snapshot(STAGE_READY, ["expected"]),
            _snapshot(STAGE_RERANKED, ["expected"]),
            _snapshot(STAGE_BOOSTED, ["expected"]),
            _snapshot(STAGE_FLOOR, []),
            _snapshot(STAGE_FINAL, []),
        ]

        self.assertEqual(find_drop_stage(trace, {"expected"}), STAGE_FLOOR)

    def test_labeled_parallel_branch_can_rescue_initial_retrieval(self) -> None:
        trace = [
            _snapshot(STAGE_GLOBAL, []),
            _snapshot(STAGE_LABELED, ["expected"]),
            _snapshot(STAGE_MERGED, []),
            _snapshot(STAGE_READY, []),
            _snapshot(STAGE_RERANKED, []),
            _snapshot(STAGE_BOOSTED, []),
            _snapshot(STAGE_FLOOR, []),
            _snapshot(STAGE_FINAL, []),
        ]

        self.assertEqual(find_drop_stage(trace, {"expected"}), STAGE_MERGED)

    def test_final_hit_has_no_drop_stage(self) -> None:
        trace = [
            _snapshot(STAGE_GLOBAL, ["expected"]),
            _snapshot(STAGE_LABELED, []),
            _snapshot(STAGE_MERGED, ["expected"]),
            _snapshot(STAGE_READY, ["expected"]),
            _snapshot(STAGE_RERANKED, ["expected"]),
            _snapshot(STAGE_BOOSTED, ["expected"]),
            _snapshot(STAGE_FLOOR, ["expected"]),
            _snapshot(STAGE_FINAL, ["expected"]),
        ]

        self.assertIsNone(find_drop_stage(trace, {"expected"}))

    def test_never_retrieved_answer_reports_initial_stage(self) -> None:
        trace = [
            _snapshot(STAGE_GLOBAL, ["other"]),
            _snapshot(STAGE_LABELED, []),
            _snapshot(STAGE_FINAL, ["other"]),
        ]

        self.assertEqual(find_drop_stage(trace, {"expected"}), STAGE_GLOBAL)

    def test_incomplete_trace_does_not_guess_a_drop_stage(self) -> None:
        trace = [
            _snapshot(STAGE_GLOBAL, ["expected"]),
            _snapshot(STAGE_LABELED, []),
            _snapshot(STAGE_MERGED, ["expected"]),
        ]

        self.assertIsNone(find_drop_stage(trace, {"expected"}))


if __name__ == "__main__":
    unittest.main()
