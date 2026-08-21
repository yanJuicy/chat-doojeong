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


def rescue_by_relative_margin(
    reranked: list[SearchResult],
    *,
    low_floor: float,
    margin: float,
) -> list[SearchResult]:
    """절대점수는 하한선 밑이어도, 다른 문서의 최고 후보보다 margin배 이상 높으면 1위 후보만 구조한다.

    실측 확인: 같은 정답 청크인데 질문 표현(유의어/격식)만 바꿔도 리랭커 절대점수가
    0.004~0.15까지 흔들린다. 절대 하한선만으로는 이런 표현 변화에 약해서, "다른 문서
    후보들보다 압도적으로 앞서는가"라는 상대적 신호를 보조로 쓴다.

    다만 상대 격차만 보면, 정답이 없는 질문에서도 노이즈 후보 하나가 다른 노이즈보다
    우연히 몇 배 높게 나와 헛답을 만들 위험이 있다 — 그래서 low_floor(순수 노이즈보다는
    확실히 높은, 그러나 기존 하한선보다는 훨씬 낮은 절대 최소선)를 반드시 같이 요구한다.
    경쟁 문서가 아예 없으면(후보가 사실상 한 문서뿐이면) 비교 대상이 없다는 뜻이라
    low_floor만 넘으면 통과시킨다 — 배수 조건 자체가 성립하지 않기 때문이다.
    """
    if low_floor <= 0 or margin <= 0 or not reranked:
        return []
    ordered = sorted(reranked, key=lambda candidate: candidate.score, reverse=True)
    top = ordered[0]
    if top.score < low_floor:
        return []
    top_document_id = str(top.metadata.get("document_id") or "")
    other_document_best = 0.0
    for candidate in ordered[1:]:
        document_id = str(candidate.metadata.get("document_id") or "")
        if document_id and document_id != top_document_id:
            other_document_best = candidate.score
            break
    if other_document_best > 0.0 and (top.score / max(other_document_best, 1e-9)) < margin:
        return []
    return [top]


def apply_relevance_floor_with_safe_rescue(
    query: str,
    first_stage: list[SearchResult],
    reranked: list[SearchResult],
    *,
    floor: float,
    top_k: int,
    explicit_document_ids: Collection[str] = (),
    relative_margin_low_floor: float = 0.0,
    relative_margin: float = 0.0,
) -> tuple[list[SearchResult], bool]:
    """고정 floor를 우선 적용하고, 전멸한 질문만 제한적으로 구조한다.

    명시 회사/제품 라벨이 있는 질문은 라벨로 확정된 문서 ID 안에서만 RRF
    후보를 구조한다. 따라서 cross-encoder의 질문별 절대점수 스케일이 낮아도
    정답 라벨 문서가 전멸하지 않으면서, 다른 엔티티 문서가 섞이지 않는다.
    라벨이 없는 질문은 상대적 격차(rescue_by_relative_margin)로 먼저 구조를
    시도하고, 그래도 안 되면 문서명에서 대상 핵심어가, 본문에서 속성 핵심어가
    각각 확인되는 후보만 구조한다.
    """
    filtered = [candidate for candidate in reranked if candidate.score >= floor]
    if not reranked:
        return filtered, False

    fused = reciprocal_rank_fuse(first_stage, reranked)
    if explicit_document_ids:
        allowed_document_ids = {str(document_id) for document_id in explicit_document_ids if document_id}
        preferred_candidates = [
            candidate
            for candidate in fused
            if str(candidate.metadata.get("document_id") or "") in allowed_document_ids
        ][: min(3, max(0, top_k))]
        existing_chunk_ids = {candidate.chunk_id for candidate in filtered}
        rescued = [candidate for candidate in preferred_candidates if candidate.chunk_id not in existing_chunk_ids]
        if not rescued:
            return filtered, False
        combined = [*filtered, *rescued]
        combined.sort(key=lambda candidate: candidate.score, reverse=True)
        return combined, True

    if filtered:
        return filtered, False

    margin_rescued = rescue_by_relative_margin(
        reranked, low_floor=relative_margin_low_floor, margin=relative_margin
    )
    if margin_rescued:
        return margin_rescued, True

    terms = query_terms(query)
    if not terms:
        return [], False

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
