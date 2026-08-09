"""
파일 확장자를 보고 알맞은 BaseDocumentExtractor 구현체를 골라주는 레지스트리.

PaddleOCR처럼 로딩이 무거운 엔진은 한 번만 만들어서 재사용하도록 캐싱한다.
새 포맷을 지원하려면 이 파일에 매핑 한 줄만 추가하면 되고,
extraction_worker나 main.py는 전혀 건드릴 필요가 없다 (여기가 "확장 지점"이다).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .document_extractor import BaseDocumentExtractor

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """확장자 -> 추출기 인스턴스를 지연 생성 + 캐싱해서 제공한다."""

    def __init__(self) -> None:
        self._cache: dict[str, BaseDocumentExtractor] = {}

    async def get_for_file(self, file_path: str) -> BaseDocumentExtractor:
        """파일 경로의 확장자를 보고 알맞은 추출기를 반환한다 (필요 시 최초 1회만 생성)."""
        ext = Path(file_path).suffix.lower()

        if ext in self._cache:
            return self._cache[ext]

        extractor = self._create_extractor(ext)
        self._cache[ext] = extractor
        return extractor

    @staticmethod
    def _create_extractor(ext: str) -> BaseDocumentExtractor:
        if ext == ".pdf":
            from ..config import settings
            from ..services.pdf_ingestion.extractor import PdfExtractor

            logger.info("PDF 추출기(PyMuPDF+PaddleOCR) 로딩")
            image_captioner = None
            if settings.pdf_image_captioning_enabled:
                from .ollama_vision_captioner import OllamaVisionCaptioner

                image_captioner = OllamaVisionCaptioner()
            return PdfExtractor(image_captioner=image_captioner)

        if ext == ".docx":
            from ..services.word_ingestion.extractor import WordExtractor

            logger.info("Word 추출기(python-docx) 로딩")
            return WordExtractor()

        if ext in (".txt", ".md"):
            from .plain_text_extractor import PlainTextExtractor

            return PlainTextExtractor()

        if ext in (".html", ".htm"):
            from ..services.html_ingestion.extractor import HtmlExtractor

            return HtmlExtractor()

        if ext in (".jpg", ".jpeg", ".png"):
            from ..config import settings
            from ..services.image_ingestion.extractor import ImageExtractor

            logger.info("이미지 추출기(OCR+캡션) 로딩")
            image_captioner = None
            if settings.direct_image_captioning_enabled:
                from .ollama_vision_captioner import OllamaVisionCaptioner

                image_captioner = OllamaVisionCaptioner()
            return ImageExtractor(image_captioner=image_captioner)

        raise ValueError(f"지원하지 않는 파일 형식입니다: {ext} (지원: .pdf, .docx, .txt, .md, .html, .jpg, .png)")


# 앱 전체에서 하나만 두고 재사용 (워커/관리자 엔드포인트가 공유)
extractor_registry = ExtractorRegistry()
