"""
이미지 파일(.jpg, .jpeg, .png)을 문서로 직접 업로드했을 때 처리하는 추출기.

두 가지를 동시에 한다:
  1. OCR로 이미지 안의 텍스트를 뽑는다 (스캔한 문서 사진일 수 있으므로).
  2. 이미지 자체도 저장해서 IMAGE_BLOCK 마커로 감싼다 (PDF 안의 그림처럼, 답변에
     썸네일+캡션으로 표시될 수 있게). OCR로 텍스트가 하나도 안 나온(순수 사진/차트인)
     경우에도 최소한 이미지 블록은 남아서 검색/표시가 가능하다.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PIL import Image

from ...config import settings
from ...core.document_extractor import BaseDocumentExtractor
from ...core.extraction_quality import choose_better_extraction, evaluate_extraction_quality
from ...core.image_captioner import BaseImageCaptioner
from ...core.image_markdown import wrap_image_block
from ...core.process_flow_enricher import enrich_numbered_process_flows
from ..table_extraction.engines.paddle_engine import PaddleTableEngine

logger = logging.getLogger(__name__)


class ImageExtractor(BaseDocumentExtractor):
    """이미지 파일 하나를 통째로 문서로 취급하는 추출기 (BaseDocumentExtractor 구현체)"""

    def __init__(
        self,
        paddle_engine: PaddleTableEngine | None = None,
        image_captioner: BaseImageCaptioner | None = None,
    ) -> None:
        self._paddle_engine = paddle_engine
        self._image_captioner = image_captioner
        self.last_page_diagnostics: list[dict] = []
        self.last_extraction_method = "image_ocr"

    async def extract(self, file_path: str, on_progress=None) -> str:  # noqa: ANN001 (선택 진행률 콜백, 이 추출기는 사용 안 함)
        image = Image.open(file_path).convert("RGB")

        ocr_text = enrich_numbered_process_flows(self._ocr_image(image))
        self.last_page_diagnostics = [
            {"page": 1, "method": "image_ocr", **evaluate_extraction_quality(ocr_text).to_dict()}
        ]

        image_bytes = Path(file_path).read_bytes()
        image_block = await self._save_and_wrap(
            image_bytes,
            image,
            Path(file_path).suffix.lstrip("."),
            context=ocr_text,
        )

        parts = [p for p in (ocr_text.strip(), image_block) if p]
        return "\n\n".join(parts)

    def _ocr_image(self, image: Image.Image) -> str:
        """이미지 안의 텍스트를 OCR로 뽑는다 (스캔한 문서 사진 등). 실패해도 전체 추출을 막지 않는다."""
        try:
            if self._paddle_engine is None:
                self._paddle_engine = PaddleTableEngine()
            # 사진/페이지 이미지의 주 목적은 본문 검색이다. 경량 한글 OCR을 먼저 쓰면
            # PPStructure가 생성한 HTML/이미지 태그가 품질 점수를 부풀리는 문제도 피한다.
            light_text = self._paddle_engine.extract_light_text(image)
            light_quality = evaluate_extraction_quality(light_text)
            if light_quality.score >= settings.ocr_fallback_min_score:
                return light_text

            logger.warning("이미지 경량 OCR 품질 낮음(score=%.3f) -> 구조화 OCR 재시도", light_quality.score)
            full_text = self._paddle_engine.extract_full_page_text(image)
            selected, quality, source = choose_better_extraction(light_text, full_text)
            logger.info("이미지 OCR 비교 완료 -> %s 선택(score=%.3f)", source, quality.score)
            return selected
        except Exception as exc:  # noqa: BLE001
            logger.warning("이미지 OCR 실패(이미지 블록만으로 계속 진행): %s", exc)
            return ""

    async def _save_and_wrap(self, image_bytes: bytes, image: Image.Image, ext: str, context: str = "") -> str:
        """
        이미지를 내용 기반 해시 파일명으로 저장하고(중복 시 재사용), 캡션과 함께 마커로 감싼다.
        캡션은 문맥(OCR로 뽑힌 텍스트)을 같이 참고해서 생성한다 — PDF 안 이미지와 동일한 원칙.
        """
        storage_dir = Path(settings.image_storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)

        image_hash = hashlib.sha256(image_bytes).hexdigest()
        ext = ext.lower() if ext.lower() in ("jpg", "jpeg", "png") else "png"
        filename = f"{image_hash}.{ext}"
        saved_path = storage_dir / filename
        if not saved_path.exists():
            saved_path.write_bytes(image_bytes)

        caption = ""
        if settings.direct_image_captioning_enabled and self._image_captioner is not None:
            caption = await self._image_captioner.caption(image, context=context[:1200])
        if not caption:
            # 내용 없는 자리표시자 청크는 실제 OCR 청크를 검색 후보에서 밀어낸다.
            # 파일은 이미 저장했으므로 캡셔닝을 켜고 재처리하면 그때 이미지 청크를 만들 수 있다.
            return ""

        return wrap_image_block(image_path=filename, caption=caption)
