"""
청킹(Chunking) 추상 인터페이스.
정확도 우선 조건에 따라 의미기반(Semantic) 청킹을 기본 전략으로 채택한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Chunk(BaseModel):
    """분할된 텍스트 청크 하나"""

    chunk_id: str
    text: str
    source_document_id: str
    page_number: int | None = None
    is_table: bool = False  # table_extraction 모듈에서 넘어온 표 청크인지 여부
    image_path: str | None = None  # 이미지(그림/차트) 캡션 청크인 경우, 원본 이미지 파일 경로
    precomputed_dense_vector: list[float] | None = None  # 청킹 단계에서 이미 계산된 벡터가 있으면 재사용 (문장 1개짜리 청크 등)
    parent_text: str | None = None  # Parent-Child 청킹: 이 청크(자식)가 속한 더 큰 맥락(부모 섹션 전체).
    # None이면 "이 청크 자체가 이미 parent 크기"라는 뜻 — 안 쪼개진 짧은 섹션에서 중복 저장 방지.


class BaseChunker(ABC):
    """텍스트를 의미 단위로 분할하는 엔진의 공통 인터페이스"""

    @abstractmethod
    async def split(self, document_id: str, text: str) -> list[Chunk]:
        """
        문서 텍스트를 청크 목록으로 분할한다.
        table_extraction 모듈이 삽입한 <!-- TABLE_BLOCK_START/END --> 마커 사이는
        반드시 하나의 청크로 유지해야 한다 (분할 금지).
        """
        raise NotImplementedError
