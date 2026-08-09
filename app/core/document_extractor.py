"""
문서에서 텍스트를 추출하는 엔진의 추상 인터페이스.

핵심 설계 의도: OCR/PDF 파싱 로직을 파이프라인 안에 감싸 넣지 않고,
"파일 경로를 넣으면 텍스트가 나온다"는 계약만 정의해서 완전히 밖으로 뺀다.
- PyMuPDF+PaddleOCR 조합(PdfExtractor)은 이 인터페이스의 구현체 중 하나일 뿐이다.
- 다른 OCR 엔진, 외부 OCR API, 사람이 수기로 입력한 텍스트 등 무엇으로 교체하든
  이 인터페이스만 만족하면 워커(app/workers/extraction_worker.py)는 코드를 한 줄도 안 고쳐도 된다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

# (현재 페이지, 전체 페이지) 를 받아서 진행률을 기록하는 콜백. 페이지 개념이 없는 포맷(txt, html 등)은 그냥 무시한다.
ProgressCallback = Callable[[int, int], Awaitable[None]]


class BaseDocumentExtractor(ABC):
    """파일 경로를 받아 텍스트(표는 정규화된 마커 포함)를 반환하는 추출기의 공통 인터페이스"""

    @abstractmethod
    async def extract(self, file_path: str, on_progress: ProgressCallback | None = None) -> str:
        """
        파일 하나에서 텍스트를 추출한다. 표는 청크 마커로 감싸진 상태로 반환되어야 한다.
        on_progress가 주어지면(선택), 페이지 단위로 진행 상황을 알려줄 수 있는 추출기(PDF 등)는
        페이지 하나 끝날 때마다 호출해서 "3/32페이지 처리 중" 같은 진행률을 밖에서 볼 수 있게 한다.
        """
        raise NotImplementedError
