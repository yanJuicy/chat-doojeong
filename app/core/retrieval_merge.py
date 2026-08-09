"""전역 검색과 라벨 범위 검색의 후보를 안전하게 합친다."""
from __future__ import annotations

from .lexical_scoring import keyword_overlap_score, query_terms
from .vector_store import SearchResult


def merge_global_and_labeled_candidates(
    global_results: list[SearchResult],
    labeled_results: list[SearchResult],
    max_count: int,
    query: str | None = None,
) -> list[SearchResult]:
    """전체 후보 약 2/3와 라벨 후보 약 1/3을 중복 없이 합친다.

    query가 주어지면 전체 100개 풀에서 질문 핵심어가 실제로 많이 등장하는
    후보를 최대 1/4 예약한다. 벡터 순위 16개 바깥의 정확한 숫자/사양 청크가
    CPU 후보 축소 과정에서 사라지는 것을 막기 위한 안전장치다.
    """
    if max_count <= 0:
        return []
    if not labeled_results and not query:
        return global_results[:max_count]

    global_quota = max(1, (max_count * 2 + 2) // 3)
    labeled_quota = max_count - global_quota
    merged: list[SearchResult] = []
    seen: set[str] = set()

    def append_unique(results: list[SearchResult], limit: int | None = None) -> None:
        added = 0
        for result in results:
            if len(merged) >= max_count or (limit is not None and added >= limit):
                break
            if result.chunk_id in seen:
                continue
            seen.add(result.chunk_id)
            merged.append(result)
            added += 1

    if query:
        terms = query_terms(query)
        lexical_pool: dict[str, SearchResult] = {
            result.chunk_id: result for result in [*global_results, *labeled_results]
        }
        scored_candidates = [
            (keyword_overlap_score(terms, result.text), result)
            for result in lexical_pool.values()
        ]
        lexical_ranked = sorted(
            scored_candidates,
            key=lambda item: (item[0], item[1].score),
            reverse=True,
        )
        protected = [result for overlap, result in lexical_ranked if overlap > 0]
        append_unique(protected, max(2, max_count // 4))

    append_unique(global_results, global_quota)
    append_unique(labeled_results, labeled_quota)
    append_unique(global_results)
    append_unique(labeled_results)
    return merged
