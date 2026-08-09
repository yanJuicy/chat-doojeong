"""
Qdrant 벡터스토어 구현체.

- "dense"와 "sparse" 두 개의 named vector를 한 컬렉션에 저장한다.
- 둘 다 주어지면 Qdrant의 내장 RRF(Reciprocal Rank Fusion)로 하이브리드 검색을 수행하고,
  sparse가 없으면 dense 단독 검색으로 폴백한다.
"""
from __future__ import annotations

import logging

from qdrant_client import AsyncQdrantClient, models

from ..config import settings
from .vector_store import BaseVectorStore, SearchResult

logger = logging.getLogger(__name__)

_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"
_DENSE_VECTOR_SIZE = 1024  # bge-m3 dense 차원 수


class QdrantVectorStore(BaseVectorStore):
    """qdrant-client(Async) 기반 벡터 저장소"""

    def __init__(self) -> None:
        self._client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self._collection_name = settings.qdrant_collection_name

    async def ensure_collection(self) -> None:
        """컬렉션이 없으면 dense+sparse 벡터 스키마로 생성한다. 앱 시작 시 한 번 호출한다."""
        exists = await self._client.collection_exists(self._collection_name)
        if exists:
            return

        await self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config={
                _DENSE_VECTOR_NAME: models.VectorParams(size=_DENSE_VECTOR_SIZE, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                _SPARSE_VECTOR_NAME: models.SparseVectorParams(),
            },
        )
        logger.info("Qdrant 컬렉션 생성 완료: %s", self._collection_name)

    async def upsert(
        self,
        chunk_id: str,
        text: str,
        dense_vector: list[float],
        sparse_vector: dict[int, float] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """청크 하나를 dense(+sparse) 벡터와 함께 저장/갱신한다."""
        vector: dict[str, object] = {_DENSE_VECTOR_NAME: dense_vector}
        if sparse_vector:
            vector[_SPARSE_VECTOR_NAME] = models.SparseVector(
                indices=list(sparse_vector.keys()),
                values=list(sparse_vector.values()),
            )

        payload = {"text": text, **(metadata or {})}

        await self._client.upsert(
            collection_name=self._collection_name,
            points=[models.PointStruct(id=chunk_id, vector=vector, payload=payload)],
        )

    async def search(
        self,
        query_dense_vector: list[float],
        query_sparse_vector: dict[int, float] | None = None,
        top_k: int = 30,
        filters: dict | None = None,
    ) -> list[SearchResult]:
        """dense(+sparse) 벡터로 유사도 검색을 수행한다."""
        query_filter = self._build_filter(filters)

        if query_sparse_vector:
            # dense/sparse 각각 후보를 넉넉히 뽑은 뒤 RRF로 병합
            response = await self._client.query_points(
                collection_name=self._collection_name,
                prefetch=[
                    models.Prefetch(
                        query=query_dense_vector,
                        using=_DENSE_VECTOR_NAME,
                        limit=top_k * 2,
                        filter=query_filter,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=list(query_sparse_vector.keys()),
                            values=list(query_sparse_vector.values()),
                        ),
                        using=_SPARSE_VECTOR_NAME,
                        limit=top_k * 2,
                        filter=query_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                query_filter=query_filter,
            )
        else:
            response = await self._client.query_points(
                collection_name=self._collection_name,
                query=query_dense_vector,
                using=_DENSE_VECTOR_NAME,
                limit=top_k,
                query_filter=query_filter,
            )

        return [
            SearchResult(
                chunk_id=str(point.id),
                text=str(point.payload.get("text", "")),
                score=point.score,
                metadata={k: v for k, v in point.payload.items() if k != "text"},
            )
            for point in response.points
        ]

    @staticmethod
    def _build_filter(filters: dict | None) -> models.Filter | None:
        """{필드: 값/값목록}을 Qdrant Filter로 변환한다. 목록은 그중 하나와 일치하면 된다."""
        if not filters:
            return None
        conditions = []
        for key, value in filters.items():
            match = models.MatchAny(any=value) if isinstance(value, list) else models.MatchValue(value=value)
            conditions.append(models.FieldCondition(key=key, match=match))
        return models.Filter(
            must=conditions
        )

    async def delete_by_document_id(self, document_id: str) -> None:
        """
        메타데이터의 document_id가 일치하는 포인트를 전부 지운다. chunk_id를 몰라도(재청킹으로
        chunk_id가 매번 새로 생성돼도) 지울 수 있는 게 핵심 — document_id로 필터링해서 지운다.
        """
        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
                )
            ),
        )
        logger.info("Qdrant에서 문서 벡터 삭제 완료: document_id=%s", document_id)
