"""평가 전용 검색 후보 스냅샷과 정답 문서 탈락 단계 계산."""
from __future__ import annotations

from collections.abc import Collection
from typing import Any

from .vector_store import SearchResult


STAGE_GLOBAL = "global_dense_sparse"
STAGE_LABELED = "labeled_search"
STAGE_MERGED = "merged_candidates"
STAGE_READY = "ready_filtered"
STAGE_RERANKED = "reranked"
STAGE_BOOSTED = "label_identifier_boosted"
STAGE_FLOOR = "floor_filtered"
STAGE_FINAL = "final_top_k"

TRACE_STAGE_ORDER = (
    STAGE_GLOBAL,
    STAGE_LABELED,
    STAGE_MERGED,
    STAGE_READY,
    STAGE_RERANKED,
    STAGE_BOOSTED,
    STAGE_FLOOR,
    STAGE_FINAL,
)


def snapshot_candidates(stage: str, candidates: Collection[SearchResult]) -> dict[str, Any]:
    """현재 순서와 점수를 값으로 복사한다. 원본 후보는 절대 수정하지 않는다."""
    return {
        "stage": stage,
        "candidates": [
            {
                "rank": rank,
                "document_id": (
                    str(candidate.metadata["document_id"])
                    if candidate.metadata.get("document_id") is not None
                    else None
                ),
                "chunk_id": str(candidate.chunk_id),
                "score": float(candidate.score),
            }
            for rank, candidate in enumerate(candidates, start=1)
        ],
    }


def expected_stage_ranks(
    trace: Collection[dict[str, Any]],
    expected_document_ids: Collection[str],
) -> dict[str, int | None]:
    """각 계측 단계에서 정답 문서가 처음 등장한 순위를 반환한다."""
    expected = {str(document_id) for document_id in expected_document_ids}
    ranks: dict[str, int | None] = {}
    for snapshot in trace:
        matching_ranks = [
            int(candidate["rank"])
            for candidate in snapshot.get("candidates", [])
            if candidate.get("document_id") in expected
        ]
        ranks[str(snapshot.get("stage"))] = min(matching_ranks) if matching_ranks else None
    return ranks


def find_drop_stage(
    trace: Collection[dict[str, Any]],
    expected_document_ids: Collection[str],
) -> str | None:
    """정답 문서가 최종 근거에 없다면 파이프라인에서 처음 제거된 단계를 찾는다.

    라벨 검색은 전역 검색과 병렬 분기이므로 단독 결과의 부재를 탈락으로 보지 않는다.
    전역 검색 후보와 라벨 후보의 합집합을 초기 검색 결과로 본 뒤, merge부터
    순차적으로 비교한다. 초기 검색 어디에도 없으면 global_dense_sparse를 반환한다.
    """
    expected = {str(document_id) for document_id in expected_document_ids}
    if not expected:
        return None

    stage_document_ids = {
        str(snapshot.get("stage")): {
            str(candidate["document_id"])
            for candidate in snapshot.get("candidates", [])
            if candidate.get("document_id") is not None
        }
        for snapshot in trace
    }

    # 파이프라인이 오류로 중단돼 최종 단계까지 도달하지 못했다면,
    # 아직 실행되지 않은 단계를 정답 문서의 탈락 원인으로 단정하지 않는다.
    if STAGE_FINAL not in stage_document_ids:
        return None

    final_ids = stage_document_ids.get(STAGE_FINAL, set())
    if expected & final_ids:
        return None

    global_ids = stage_document_ids.get(STAGE_GLOBAL, set())
    labeled_ids = stage_document_ids.get(STAGE_LABELED, set())
    initial_ids = global_ids | labeled_ids

    if not expected & initial_ids:
        return STAGE_GLOBAL

    previous_ids = initial_ids
    for stage in (
        STAGE_MERGED,
        STAGE_READY,
        STAGE_RERANKED,
        STAGE_BOOSTED,
        STAGE_FLOOR,
        STAGE_FINAL,
    ):
        current_ids = stage_document_ids.get(stage, set())
        if expected & previous_ids and not expected & current_ids:
            return stage
        previous_ids = current_ids

    return STAGE_FINAL
