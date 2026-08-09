"""
벡터DB(Vector Store) 추상 인터페이스.
Qdrant 구현체는 이 인터페이스를 상속한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class SearchResult(BaseModel):
    """벡터 검색 결과 하나"""

    chunk_id: str
    text: str
    score: float
    metadata: dict


class BaseVectorStore(ABC):
    """벡터 저장/검색을 담당하는 저장소의 공통 인터페이스"""

    @abstractmethod
    async def upsert(
        self,
        chunk_id: str,
        text: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """청크 하나를 벡터DB에 저장/갱신한다."""
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query_dense_vector: list[float],
        query_sparse_vector: dict[int, float] | None = None,
        top_k: int = 30,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        """dense(+sparse) 벡터로 유사도 검색을 수행한다. filters로 메타데이터 조건을 걸 수 있다."""
        raise NotImplementedError

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> None:
        """특정 문서에 속한 청크 벡터를 전부 지운다 (문서 재처리/라벨 수정 시, 옛 벡터가 남지 않게)."""
        raise NotImplementedError
