"""
임베딩 모델 추상 인터페이스.
구현체(bge-m3 등)는 이 인터페이스를 상속해서 작성한다. (models/bge_m3.py 등으로 분리 예정)
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """텍스트를 벡터로 변환하는 임베딩 엔진의 공통 인터페이스"""

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """문서(청크) 목록을 dense 벡터 목록으로 변환한다."""
        raise NotImplementedError

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """검색 질의 하나를 dense 벡터로 변환한다."""
        raise NotImplementedError

    @abstractmethod
    async def embed_hybrid(self, texts: list[str]) -> tuple[list[list[float]], list[dict[int, float]]]:
        """한 번의 모델 추론으로 dense+sparse 벡터를 함께 반환한다."""
        raise NotImplementedError

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        텍스트가 실제로 몇 개의 토큰으로 쪼개지는지 센다 (글자 수 근사가 아니라 실제 토크나이저 기준).
        청킹 시 "최대 토큰 수"를 정확히 지키기 위해 쓴다. 동기 함수라 임베딩 계산 없이 빠르게 호출 가능하다.
        """
        raise NotImplementedError
