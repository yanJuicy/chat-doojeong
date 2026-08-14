from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.core.question_cache import (
    QuerySignature,
    SemanticQuestionCache,
    build_query_signature,
)


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 11, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def signature(
    *,
    identifiers: set[str] | None = None,
    labels: set[str] | None = None,
    attributes: set[str] | None = None,
    query_type: str = "single_lookup",
    intent: str = "specification",
) -> QuerySignature:
    return QuerySignature(
        identifiers=frozenset(identifiers or set()),
        labels=frozenset(labels or set()),
        attributes=frozenset(attributes or {"payload"}),
        query_type=query_type,
        intent=intent,
    )


class SemanticQuestionCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        self.cache = SemanticQuestionCache(
            max_size=10,
            ttl=timedelta(hours=48),
            similarity_threshold=0.92,
            now_provider=self.clock.now,
        )

    def store(self, *, cached_signature: QuerySignature | None = None, document_id: str = "doc-1"):
        return self.cache.store(
            question="VTX-310의 가반하중은 얼마인가요?",
            question_vector=[1.0, 0.0, 0.0],
            answer="10kg입니다.",
            signature=cached_signature or signature(identifiers={"vtx-310"}),
            source_document_ids={document_id},
            source_chunk_ids={"chunk-1"},
            n_context_chunks=1,
            images=[],
            sources=[],
            intent_scores=[{"category": "specification", "similarity": 0.9}],
        )

    def test_paraphrase_hits_when_similarity_and_safety_metadata_match(self) -> None:
        self.store()

        hit = self.cache.get_semantic(
            [0.99, 0.01, 0.0],
            signature(identifiers={"vtx-310"}),
        )

        self.assertIsNotNone(hit)
        self.assertGreater(hit.similarity, 0.99)
        self.assertEqual("10kg입니다.", hit.entry.answer)

    def test_identifier_mismatch_is_a_miss(self) -> None:
        self.store()

        hit = self.cache.get_semantic(
            [1.0, 0.0, 0.0],
            signature(identifiers={"vtx-410"}),
        )

        self.assertIsNone(hit)

    def test_attribute_mismatch_is_a_miss(self) -> None:
        self.store()

        hit = self.cache.get_semantic(
            [1.0, 0.0, 0.0],
            signature(identifiers={"vtx-310"}, attributes={"reach"}),
        )

        self.assertIsNone(hit)

    def test_label_mismatch_is_a_miss(self) -> None:
        self.store(cached_signature=signature(identifiers={"vtx-310"}, labels={"두정테크"}))

        hit = self.cache.get_semantic(
            [1.0, 0.0, 0.0],
            signature(identifiers={"vtx-310"}, labels={"다른회사"}),
        )

        self.assertIsNone(hit)

    def test_primary_intent_mismatch_is_a_miss(self) -> None:
        self.store()

        hit = self.cache.get_semantic(
            [1.0, 0.0, 0.0],
            signature(identifiers={"vtx-310"}, intent="maintenance_support"),
        )

        self.assertIsNone(hit)

    def test_comparison_and_single_lookup_are_not_compatible(self) -> None:
        self.store()

        hit = self.cache.get_semantic(
            [1.0, 0.0, 0.0],
            signature(identifiers={"vtx-310"}, query_type="comparison"),
        )

        self.assertIsNone(hit)

    def test_expired_entry_is_a_miss_and_is_deleted(self) -> None:
        self.store()
        self.clock.advance(hours=49)

        hit = self.cache.get_semantic(
            [1.0, 0.0, 0.0],
            signature(identifiers={"vtx-310"}),
        )

        self.assertIsNone(hit)
        self.assertEqual(0, len(self.cache))

    def test_hit_refreshes_sliding_ttl(self) -> None:
        entry = self.store()
        original_expiry = entry.expires_at
        self.clock.advance(hours=24)

        hit = self.cache.get_exact("  VTX-310의  가반하중은 얼마인가요?  ")

        self.assertIsNotNone(hit)
        self.assertEqual(self.clock.now(), entry.last_used_at)
        self.assertEqual(self.clock.now() + timedelta(hours=48), entry.expires_at)
        self.assertGreater(entry.expires_at, original_expiry)

    def test_source_document_invalidation_removes_only_referencing_entries(self) -> None:
        self.store(document_id="doc-1")
        self.cache.store(
            question="KX-41의 가반하중은?",
            question_vector=[0.0, 1.0, 0.0],
            answer="5kg입니다.",
            signature=signature(identifiers={"kx-41"}),
            source_document_ids={"doc-2"},
            source_chunk_ids={"chunk-2"},
            n_context_chunks=1,
            images=[],
            sources=[],
            intent_scores=[{"category": "specification", "similarity": 0.9}],
        )

        removed = self.cache.invalidate_document("doc-1")

        self.assertEqual(1, removed)
        self.assertEqual(1, len(self.cache))
        self.assertEqual(frozenset({"doc-2"}), self.cache.entries[0].source_document_ids)

    def test_signature_reuses_identifier_label_attribute_and_query_type_utilities(self) -> None:
        built = build_query_signature(
            "별하 VTX-310과 VTX-410의 작업반경 차이를 ISO 9001 인증 기준으로 비교해줘",
            available_labels=["별하자동화", "VTX-310", "VTX-410"],
            intent_scores=[{"category": "comparison_selection", "similarity": 0.91}],
        )

        self.assertEqual(frozenset({"vtx-310", "vtx-410", "iso-9001"}), built.identifiers)
        self.assertEqual(frozenset({"별하자동화", "VTX-310", "VTX-410"}), built.labels)
        self.assertEqual(frozenset({"reach", "certification"}), built.attributes)
        self.assertEqual("comparison", built.query_type)
        self.assertEqual("comparison_selection", built.intent)


if __name__ == "__main__":
    unittest.main()
