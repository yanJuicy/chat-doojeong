"""GPU가 없을 때 사용하는 빠른 하이브리드 재정렬기.

Qdrant의 BGE-M3 dense+sparse RRF 순위를 바탕으로, 질문 핵심어의 실제
등장률과 명시 라벨 문서 여부를 결합한다. 대형 cross-encoder를 CPU에서
돌리는 것보다 훨씬 빠르고 숫자·사양·공정명처럼 정확한 문자열 근거를
놓치지 않는 데 유리하다.
"""
from __future__ import annotations

from collections.abc import Collection

from .lexical_scoring import keyword_overlap_score, query_terms
from .vector_store import SearchResult


def lightweight_rerank(
    query: str,
    candidates: list[SearchResult],
    preferred_document_ids: Collection[str] = (),
) -> list[SearchResult]:
    """RRF 10% + 전체 핵심어 45% + 질문 뒤쪽 속성어 30% + 문서 힌트 15%.

    이 함수는 CPU 전용 안전 경로다. 의미 검색은 이미 BGE-M3 dense+sparse가
    끝낸 상태이므로, 여기서는 대형 리랭커가 잘 놓치는 정확한 사양명·숫자·
    공정 단어의 실제 등장을 더 강하게 본다.
    """
    if not candidates:
        return []

    preferred = set(preferred_document_ids)
    terms = query_terms(query)
    attribute_terms = terms[-3:]
    scores = [candidate.score for candidate in candidates]
    low, high = min(scores), max(scores)
    span = high - low
    rescored: list[SearchResult] = []

    for rank, candidate in enumerate(candidates):
        if span > 1e-12:
            semantic = (candidate.score - low) / span
        else:
            semantic = 1.0 - (rank / max(1, len(candidates)))
        metadata_text = " ".join(str(value) for value in candidate.metadata.values())
        candidate_text = f"{candidate.text} {metadata_text}"
        lexical = keyword_overlap_score(terms, candidate_text)
        # 한국어 제품 질문은 보통 "회사/제품 + 묻는 속성" 순서다. 마지막 세
        # 핵심어를 별도로 보아, 제품명만 반복하는 소개 청크보다 "최대 주행
        # 속도"처럼 실제 답을 담은 사양 청크를 우선한다.
        attribute = keyword_overlap_score(attribute_terms, candidate_text)
        preferred_bonus = 1.0 if candidate.metadata.get("document_id") in preferred else 0.0
        combined = 0.10 * semantic + 0.45 * lexical + 0.30 * attribute + 0.15 * preferred_bonus
        rescored.append(candidate.model_copy(update={"score": min(1.0, combined)}))

    rescored.sort(key=lambda result: result.score, reverse=True)
    return rescored
