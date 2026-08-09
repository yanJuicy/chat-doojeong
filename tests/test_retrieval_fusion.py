from __future__ import annotations

import unittest

from app.core.retrieval_fusion import (
    apply_relevance_floor_with_safe_rescue,
    reciprocal_rank_fuse,
    rescue_broad_lexical_candidates,
)
from app.core.vector_store import SearchResult


def _result(
    chunk_id: str,
    text: str,
    score: float,
    *,
    filename: str = "",
    document_id: str = "doc",
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        text=text,
        score=score,
        metadata={"document_id": document_id, "filename": filename},
    )


class RetrievalFusionTests(unittest.TestCase):
    def test_rrf_restores_candidate_strong_in_first_stage(self) -> None:
        first_stage = [
            _result("answer", "정답", 0.59),
            *[_result(f"other-{index}", "기타", 0.5 - index / 100) for index in range(7, 0, -1)],
        ]
        reranked = [
            *[_result(f"other-{index}", "기타", 0.03 - index / 1000) for index in range(1, 7)],
            _result("answer", "정답", 0.02),
            _result("other-7", "기타", 0.01),
        ]

        fused = reciprocal_rank_fuse(first_stage, reranked)

        self.assertEqual(fused[0].chunk_id, "answer")
        self.assertEqual(first_stage[0].score, 0.59)
        self.assertEqual(reranked[6].score, 0.02)

    def test_existing_floor_passes_without_changing_scores_or_order(self) -> None:
        reranked = [
            _result("one", "본문", 0.9),
            _result("two", "본문", 0.3),
            _result("low", "본문", 0.1),
        ]

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "질문",
            reranked,
            reranked,
            floor=0.2,
            top_k=5,
        )

        self.assertFalse(rescued)
        self.assertEqual([(item.chunk_id, item.score) for item in selected], [("one", 0.9), ("two", 0.3)])

    def test_floor_empty_q17_shape_is_rescued_by_identity_and_attribute(self) -> None:
        answer = _result(
            "answer",
            "주행 속도 최대 1.0m/s (조절 가능)",
            0.59,
            filename="서빙로봇 카탈로그.pdf",
            document_id="serving",
        )
        distractors = [
            _result(f"other-{index}", "일반 로봇 소개", 0.5 - index / 100, filename="로봇 소개.pdf")
            for index in range(1, 8)
        ]
        first_stage = [answer, *distractors]
        reranked = [
            *[item.model_copy(update={"score": 0.03 - index / 1000}) for index, item in enumerate(distractors[:6], start=1)],
            answer.model_copy(update={"score": 0.02}),
            distractors[6].model_copy(update={"score": 0.01}),
        ]

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "가장 빠른 서빙로봇 속도가 초당 몇 미터야?",
            first_stage,
            reranked,
            floor=0.2,
            top_k=5,
        )

        self.assertTrue(rescued)
        self.assertEqual([item.chunk_id for item in selected], ["answer"])

    def test_explicit_entity_question_is_not_rescued(self) -> None:
        candidate = _result(
            "wrong-entity",
            "주행 속도 최대 1.0m/s",
            0.01,
            filename="서빙로봇 카탈로그.pdf",
            document_id="serving",
        )

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "두정테크 로봇 팔의 최대 속도는 몇 m/s야?",
            [candidate],
            [candidate],
            floor=0.2,
            top_k=5,
            explicit_document_ids={"doojung-doc"},
        )

        self.assertFalse(rescued)
        self.assertEqual(selected, [])

    def test_explicit_entity_floor_empty_rescues_only_matching_document(self) -> None:
        matching = _result(
            "matching-process",
            "절연테스트 다음 단계는 출하검사",
            0.04,
            filename="선다인테크 제조공정.pdf",
            document_id="sundyne-doc",
        )
        other = _result(
            "other-process",
            "절연테스트 다음 단계는 포장",
            0.05,
            filename="다른 회사 제조공정.pdf",
            document_id="other-doc",
        )

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "제조공정에서 절연테스트 다음 단계가 뭐야?",
            [matching, other],
            [other, matching],
            floor=0.2,
            top_k=5,
            explicit_document_ids={"sundyne-doc"},
        )

        self.assertTrue(rescued)
        self.assertEqual([candidate.chunk_id for candidate in selected], ["matching-process"])

    def test_explicit_entity_is_preserved_when_unrelated_candidate_passes_floor(self) -> None:
        matching = _result(
            "matching-range",
            "최대 작업 반경 1,184 mm",
            0.04,
            filename="별하자동화 KX-41.pdf",
            document_id="byeolha-doc",
        )
        unrelated = _result(
            "unrelated-range",
            "RB 로봇 작업 반경 1,300 mm",
            0.8,
            filename="RB 매뉴얼.pdf",
            document_id="rb-doc",
        )

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "별하 로봇 팔은 몇 mm까지 뻗나?",
            [matching, unrelated],
            [unrelated, matching],
            floor=0.2,
            top_k=5,
            explicit_document_ids={"byeolha-doc"},
        )

        self.assertTrue(rescued)
        self.assertEqual({candidate.chunk_id for candidate in selected}, {"matching-range", "unrelated-range"})

    def test_candidate_without_filename_identity_is_not_rescued(self) -> None:
        candidate = _result("generic", "주행 속도 최대 1.0m/s", 0.01, filename="제품 사양.pdf")

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "가장 빠른 서빙로봇 속도가 초당 몇 미터야?",
            [candidate],
            [candidate],
            floor=0.2,
            top_k=5,
        )

        self.assertFalse(rescued)
        self.assertEqual(selected, [])

    def test_candidate_without_body_attribute_is_not_rescued(self) -> None:
        candidate = _result("title-only", "서빙로봇 제품 소개", 0.01, filename="서빙로봇 카탈로그.pdf")

        selected, rescued = apply_relevance_floor_with_safe_rescue(
            "가장 빠른 서빙로봇 속도가 초당 몇 미터야?",
            [candidate],
            [candidate],
            floor=0.2,
            top_k=5,
        )

        self.assertFalse(rescued)
        self.assertEqual(selected, [])

    def test_broad_lexical_rescue_uses_supported_document_and_distinct_attribute(self) -> None:
        first_stage = [
            _result("intro", "서빙로봇 소개", 0.59, filename="서빙로봇 카탈로그.pdf", document_id="serving"),
            _result("other", "일반 소개", 0.5, filename="기타.pdf", document_id="other"),
        ]
        lexical_candidates = [
            _result("title-only", "서빙로봇 제품 소개", 0.0, filename="서빙로봇 카탈로그.pdf", document_id="serving"),
            _result("speed", "주행 속도 최대 1.0m/s", 0.0, filename="서빙로봇 카탈로그.pdf", document_id="serving"),
            _result("unsupported", "주행 속도 최대 2.0m/s", 0.0, filename="서빙로봇 신제품.pdf", document_id="unknown"),
        ]

        rescued = rescue_broad_lexical_candidates(
            "가장 빠른 서빙로봇 속도가 초당 몇 미터야?",
            first_stage,
            lexical_candidates,
            top_k=5,
        )

        self.assertEqual([candidate.chunk_id for candidate in rescued], ["speed"])


if __name__ == "__main__":
    unittest.main()
