"""질문의 후보 검색과 리랭킹을 한 곳에서 관리한다."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, or_, select

from ..config import settings
from ..db.models import Document, DocumentChunk, DocumentLabel, DocumentStatus
from ..db.session import async_session_factory
from .bge_reranker import BgeRerankerV2
from .identifier_matching import boost_exact_identifiers
from .label_matching import find_question_label_hints
from .lexical_scoring import query_terms
from .lightweight_reranker import lightweight_rerank
from .retrieval_fusion import apply_relevance_floor_with_safe_rescue, rescue_broad_lexical_candidates
from .retrieval_merge import merge_global_and_labeled_candidates
from .retrieval_selection import select_diverse_results
from .vector_store import BaseVectorStore, SearchResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CandidateBatch:
    candidates: list[SearchResult]
    labeled_document_ids: list[str]


async def _find_explicit_question_labels(question: str) -> list[str]:
    async with async_session_factory() as session:
        result = await session.execute(select(DocumentLabel.label).distinct())
    labels = [label for (label,) in result.all() if label]
    return find_question_label_hints(question, labels)


async def _find_labeled_document_ids(labels: list[str]) -> list[str]:
    if not labels:
        return []
    async with async_session_factory() as session:
        exact_result = await session.execute(
            select(DocumentLabel.document_id)
            .where(DocumentLabel.label.in_(labels))
            .group_by(DocumentLabel.document_id)
            .having(func.count(func.distinct(DocumentLabel.label)) == len(labels))
        )
        document_ids = [row[0] for row in exact_result.all()]
        if document_ids:
            return document_ids
        partial_result = await session.execute(
            select(DocumentLabel.document_id)
            .where(DocumentLabel.label.in_(labels))
            .group_by(DocumentLabel.document_id)
            .order_by(func.count(func.distinct(DocumentLabel.label)).desc())
            .limit(100)
        )
        return [row[0] for row in partial_result.all()]


async def retrieve_candidates(
    question: str,
    query_dense: list[float],
    query_sparse: dict[int, float],
    vector_store: BaseVectorStore,
    reranker: BgeRerankerV2,
) -> CandidateBatch:
    """전역·라벨 검색을 병합하고 READY 문서의 후보만 반환한다."""
    explicit_labels = await _find_explicit_question_labels(question)
    labeled_document_ids = await _find_labeled_document_ids(explicit_labels)
    if labeled_document_ids:
        logger.info(
            "질문 라벨 감지 -> 전역 검색과 문서 %d개의 범위 검색 병행: %s",
            len(labeled_document_ids),
            explicit_labels,
        )

    global_candidates = await vector_store.search(
        query_dense_vector=query_dense,
        query_sparse_vector=query_sparse,
        top_k=settings.adaptive_retrieval_fetch_pool,
        filters=None,
    )
    labeled_candidates: list[SearchResult] = []
    if labeled_document_ids:
        labeled_candidates = await vector_store.search(
            query_dense_vector=query_dense,
            query_sparse_vector=query_sparse,
            top_k=settings.adaptive_retrieval_fetch_pool,
            filters={"document_id": labeled_document_ids},
        )
    candidate_limit = settings.adaptive_retrieval_max
    if settings.reranker_enabled and not reranker.using_cuda:
        candidate_limit = min(candidate_limit, settings.adaptive_retrieval_max_cpu)
        logger.info("CPU 리랭커 후보 자동 축소: %d개", candidate_limit)
    raw_candidates = merge_global_and_labeled_candidates(
        global_candidates,
        labeled_candidates,
        candidate_limit,
        query=question,
    )
    raw_document_ids = {
        result.metadata.get("document_id")
        for result in raw_candidates
        if result.metadata.get("document_id")
    }
    ready_document_ids: set[str] = set()
    ready_filenames: dict[str, str] = {}
    if raw_document_ids:
        async with async_session_factory() as session:
            ready_result = await session.execute(
                select(Document.id, Document.filename).where(
                    Document.id.in_(raw_document_ids),
                    Document.status == DocumentStatus.READY,
                )
            )
            ready_rows = ready_result.all()
            ready_document_ids = {row[0] for row in ready_rows}
            ready_filenames = {row[0]: row[1] for row in ready_rows}

    candidates = [
        result
        for result in raw_candidates
        if result.metadata.get("document_id") in ready_document_ids
    ]
    for result in candidates:
        document_id = result.metadata.get("document_id")
        if document_id in ready_filenames:
            result.metadata["filename"] = ready_filenames[document_id]
    return CandidateBatch(candidates=candidates, labeled_document_ids=labeled_document_ids)


async def _search_broad_lexical_chunks(question: str, limit: int = 256) -> list[SearchResult]:
    terms = query_terms(question)
    if not terms:
        return []
    async with async_session_factory() as session:
        result = await session.execute(
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.status == DocumentStatus.READY,
                or_(
                    *(DocumentChunk.text.ilike(f"%{term}%") for term in terms),
                    *(Document.filename.ilike(f"%{term}%") for term in terms),
                ),
            )
            .limit(limit)
        )
        rows = result.all()
    return [
        SearchResult(
            chunk_id=chunk.id,
            text=chunk.text,
            score=0.0,
            metadata={
                "document_id": chunk.document_id,
                "filename": filename,
                "page_number": chunk.page_number,
                "image_path": chunk.image_path,
            },
        )
        for chunk, filename in rows
    ]


async def rerank_candidates(
    question: str,
    batch: CandidateBatch,
    reranker: BgeRerankerV2,
) -> list[SearchResult]:
    """후보 전체를 점수화한 뒤 보수적 가산점·하한·다양화를 적용한다."""
    candidates = batch.candidates
    labeled_document_ids = batch.labeled_document_ids
    if settings.reranker_enabled and reranker.using_cuda:
        reranked = await reranker.rerank(
            query=question,
            candidates=candidates,
            top_k=len(candidates),
            preferred_document_ids=labeled_document_ids,
        )
    elif settings.reranker_enabled:
        reranked = lightweight_rerank(
            question,
            candidates,
            preferred_document_ids=labeled_document_ids,
        )
    else:
        reranked = candidates
    if labeled_document_ids and settings.explicit_label_boost_weight > 0:
        labeled_id_set = set(labeled_document_ids)
        for result in reranked:
            if result.metadata.get("document_id") in labeled_id_set:
                result.score = min(1.0, result.score + settings.explicit_label_boost_weight)
        reranked.sort(key=lambda result: result.score, reverse=True)
    boost_exact_identifiers(reranked, question, settings.exact_identifier_boost_weight)

    reranked, floor_rescue_applied = apply_relevance_floor_with_safe_rescue(
        question,
        candidates,
        reranked,
        floor=settings.adaptive_retrieval_floor_similarity,
        top_k=settings.reranker_top_k,
        explicit_document_ids=labeled_document_ids,
    )
    if not reranked and not labeled_document_ids:
        broad_candidates = await _search_broad_lexical_chunks(question)
        reranked = rescue_broad_lexical_candidates(
            question,
            candidates,
            broad_candidates,
            top_k=settings.reranker_top_k,
        )
        floor_rescue_applied = bool(reranked)
    if floor_rescue_applied:
        logger.info("리랭커 floor 전멸 안전 구조 적용: 후보=%d", len(reranked))
    reranked = select_diverse_results(
        reranked,
        top_k=settings.reranker_top_k,
        max_per_document=settings.retrieval_max_chunks_per_document,
        preferred_document_ids=labeled_document_ids,
        preferred_min_count=3 if labeled_document_ids else 0,
    )
    return reranked
