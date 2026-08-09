"""
리랭커(Re-ranker) 추상 인터페이스.
bge-reranker-v2-m3 구현체는 이 인터페이스를 상속한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection

from .vector_store import SearchResult


class BaseReranker(ABC):
    """1차 검색 결과를 정밀 재정렬하는 엔진의 공통 인터페이스"""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int = 5,
        preferred_document_ids: Collection[str] = (),
    ) -> list[SearchResult]:
        """
        query와 candidates의 연관도를 Cross-encoder로 재계산해서 상위 top_k개만 반환한다.
        preferred_document_ids는 구현체가 명시적으로 선호할 문서를 전달하는 선택 힌트다.
        반환된 SearchResult의 score는 리랭커 점수로 덮어써야 한다.
        """
        raise NotImplementedError
