"""리랭커 절대점수 전멸 시 사용하는 보수적인 순위 융합 안전망."""
from __future__ import annotations

from collections.abc import Collection

from .lexical_scoring import keyword_overlap_score, match_query_terms, query_terms
from .vector_store import SearchResult


def reciprocal_rank_fuse(
    first_stage: list[SearchResult],
    reranked: list[SearchResult],
    *,
    rank_constant: int = 60,
    first_stage_weight: float = 1.0,
    reranker_weight: float = 1.0,
) -> list[SearchResult]:
    """1차 검색과 cross-encoder 순위를 RRF로 결합한다.

    서로 의미가 다른 dense+sparse 점수와 cross-encoder 점수를 직접 더하지
    않고 순위만 결합한다. 반환 점수는 두 목록 모두 1위일 때 1.0이 되도록
    정규화하며 입력 SearchResult는 수정하지 않는다.
    """
    if not reranked:
        return []

    rank_constant = max(1, int(rank_constant))
    first_ranks = {candidate.chunk_id: rank for rank, candidate in enumerate(first_stage, start=1)}
    missing_rank = len(first_stage) + 1
    maximum = (first_stage_weight + reranker_weight) / (rank_constant + 1)

    fused: list[SearchResult] = []
    for reranker_rank, candidate in enumerate(reranked, start=1):
        first_rank = first_ranks.get(candidate.chunk_id, missing_rank)
        raw_score = (
            first_stage_weight / (rank_constant + first_rank)
            + reranker_weight / (rank_constant + reranker_rank)
        )
        normalized_score = raw_score / maximum if maximum > 0 else 0.0
        fused.append(candidate.model_copy(update={"score": float(normalized_score)}))

    fused.sort(key=lambda candidate: candidate.score, reverse=True)
    return fused


def apply_relevance_floor_with_safe_rescue(
    query: str,
    first_stage: list[SearchResult],
    reranked: list[SearchResult],
    *,
    floor: float,
    top_k: int,
    explicit_document_ids: Collection[str] = (),
) -> tuple[list[SearchResult], bool]:
    """고정 floor를 우선 적용하고, 전멸한 무라벨 질문만 제한적으로 구조한다.

    명시 회사/제품 라벨이 있는 질문은 잘못된 다른 엔티티의 문서를 구조하면
    환각으로 이어질 수 있어 기존처럼 빈 결과를 유지한다. 라벨이 없는 질문도
    문서명에서 대상 핵심어가, 본문에서 속성 핵심어가 각각 확인되는 후보만
    RRF 순위로 구조한다.
    """
    filtered = [candidate for candidate in reranked if candidate.score >= floor]
    if filtered or not reranked or explicit_document_ids:
        return filtered, False

    terms = query_terms(query)
    if not terms:
        return [], False

    fused = reciprocal_rank_fuse(first_stage, reranked)
    rescued: list[SearchResult] = []
    for candidate in fused:
        filename_terms = match_query_terms(terms, str(candidate.metadata.get("filename") or ""))
        body_terms = match_query_terms(terms, candidate.text)
        # 문서명과 본문에 같은 대상어만 반복된 소개/FAQ 청크는 근거가 아니다.
        # 문서명으로 대상을 확인하고, 본문에서는 그와 다른 속성어가 확인돼야 한다.
        if filename_terms and body_terms - filename_terms:
            rescued.append(candidate)
        if len(rescued) >= max(0, top_k):
            break
    return rescued, bool(rescued)


def rescue_broad_lexical_candidates(
    query: str,
    first_stage: list[SearchResult],
    lexical_candidates: list[SearchResult],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[SearchResult]:
    """전멸한 무라벨 질문에서 1차검색이 지지한 문서의 속성 청크만 구조한다.

    청크가 1차 검색 상위 풀 밖에 있어도 같은 문서의 다른 청크가 의미 검색에
    잡혔다면 문서 단위 순위를 신뢰 신호로 쓴다. broad lexical 순위와 그 문서
    순위를 RRF로 결합해, 문서 정체성과 실제 속성 내용이 모두 맞는 청크를 고른다.
    """
    terms = query_terms(query)
    if not terms or not first_stage or not lexical_candidates or top_k <= 0:
        return []

    document_ranks: dict[str, int] = {}
    for rank, candidate in enumerate(first_stage, start=1):
        document_id = str(candidate.metadata.get("document_id") or "")
        if document_id:
            document_ranks.setdefault(document_id, rank)

    evidence_candidates: list[tuple[float, SearchResult]] = []
    for candidate in lexical_candidates:
        document_id = str(candidate.metadata.get("document_id") or "")
        if document_id not in document_ranks:
            continue
        filename = str(candidate.metadata.get("filename") or "")
        filename_terms = match_query_terms(terms, filename)
        body_terms = match_query_terms(terms, candidate.text)
        if not filename_terms or not body_terms - filename_terms:
            continue
        coverage = keyword_overlap_score(terms, f"{filename} {candidate.text}")
        evidence_candidates.append((coverage, candidate))

    evidence_candidates.sort(key=lambda item: item[0], reverse=True)
    maximum = 2.0 / (max(1, rank_constant) + 1)
    rescued: list[SearchResult] = []
    for lexical_rank, (_, candidate) in enumerate(evidence_candidates, start=1):
        document_id = str(candidate.metadata.get("document_id") or "")
        raw_score = (
            1.0 / (rank_constant + document_ranks[document_id])
            + 1.0 / (rank_constant + lexical_rank)
        )
        rescued.append(candidate.model_copy(update={"score": float(raw_score / maximum)}))
        if len(rescued) >= top_k:
            break
    return rescued
