"""최종 RAG 근거가 한 문서의 유사 청크로 도배되지 않게 선택한다."""
from __future__ import annotations

from collections.abc import Collection

from .vector_store import SearchResult


def select_diverse_results(
    results: list[SearchResult],
    top_k: int,
    max_per_document: int,
    preferred_document_ids: Collection[str] = (),
    preferred_min_count: int = 0,
) -> list[SearchResult]:
    """문서별 소프트 상한으로 다양화하되, 자리가 남으면 관련 청크로 다시 채운다.

    회사/제품명이 질문에 명시된 경우 해당 라벨 문서 근거를 먼저 일정 수
    확보한다. 나머지 자리는 계속 전역 결과가 차지할 수 있으므로 하드 필터는 아니다.
    """
    selected: list[SearchResult] = []
    seen_chunks: set[str] = set()
    document_counts: dict[str, int] = {}

    preferred = set(preferred_document_ids)

    def add(result: SearchResult) -> bool:
        if result.chunk_id in seen_chunks:
            return False
        document_id = str(result.metadata.get("document_id") or "")
        if document_id and document_counts.get(document_id, 0) >= max_per_document:
            return False
        seen_chunks.add(result.chunk_id)
        if document_id:
            document_counts[document_id] = document_counts.get(document_id, 0) + 1
        selected.append(result)
        return True

    if preferred and preferred_min_count > 0:
        for result in results:
            if len(selected) >= min(top_k, preferred_min_count):
                break
            if result.metadata.get("document_id") in preferred:
                add(result)

    for result in results:
        if len(selected) >= top_k:
            break
        add(result)

    # 관련 문서가 하나뿐인 질문에서 하드 상한 때문에 컨텍스트가 3개로 줄어드는 것은 손해다.
    # 1차로 문서 다양성을 확보한 뒤 빈 자리만 원래 점수 순서대로 다시 채운다.
    if len(selected) < top_k:
        for result in results:
            if len(selected) >= top_k:
                break
            if result.chunk_id in seen_chunks:
                continue
            seen_chunks.add(result.chunk_id)
            selected.append(result)
    return selected
