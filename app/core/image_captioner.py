"""이미지(그림/차트)에 대한 설명 텍스트(캡션)를 생성하는 엔진의 추상 인터페이스."""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class BaseImageCaptioner(ABC):
    """이미지를 받아 검색 가능한 설명 문장을 반환하는 캡셔너의 공통 인터페이스"""

    @abstractmethod
    async def caption(self, image: Image.Image, context: str = "") -> str:
        """
        이미지 하나에 대한 한국어 설명 문장을 생성한다.

        Args:
            image: 캡션을 만들 이미지
            context: 이미지가 등장한 페이지의 주변 텍스트(문맥). 같은 이미지라도 문맥에 따라
                     캡션이 달라질 수 있으므로, 이미지 자체는 재사용해도 캡션은 항상 문맥을
                     반영해서 새로 만들어야 한다 (캡션 캐싱 금지).
        """
        raise NotImplementedError

