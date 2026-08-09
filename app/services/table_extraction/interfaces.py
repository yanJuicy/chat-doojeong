"""
표 추출 엔진 추상 인터페이스.
PaddleOCR / Vision-LLM 등 실제 구현체를 교체 가능하도록 분리한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image

from .models import TableBlock


class BaseTableEngine(ABC):
    """표 구조 추출 엔진의 공통 인터페이스"""

    @abstractmethod
    async def extract(self, image: Image.Image, page_number: int) -> list[TableBlock]:
        """
        이미지 한 페이지에서 표를 검출하고 구조(행/열/셀 텍스트)를 추출한다.

        Args:
            image: 페이지 이미지 (PIL Image)
            page_number: 원본 문서 내 페이지 번호

        Returns:
            검출된 TableBlock 목록 (표가 없으면 빈 리스트)
        """
        raise NotImplementedError
