"""
PDF 문서에서 텍스트를 추출한다.

- 텍스트 레이어가 있는 페이지(디지털 PDF): PyMuPDF로 바로 텍스트 추출 (빠르고 정확함, OCR 불필요)
  + 페이지에 삽입된 이미지(그림/차트/사진)도 추출해서 파일로 저장하고, 캡션과 함께
    <!-- IMAGE_BLOCK_START/END --> 마커로 감싸 본문에 원래 위치와 비슷한 자리에 끼워 넣는다.
    - 파일 저장은 이미지 내용의 해시를 파일명으로 써서(내용 기반 주소화), 완전히 같은 이미지가
      여러 문서/페이지에 반복돼도 디스크에는 한 번만 저장된다.
    - 다만 캡션은 등장할 때마다 그 페이지의 주변 텍스트(문맥)를 같이 참고해서 새로 생성한다.
      같은 그림이라도 등장하는 문맥에 따라 의미가 다를 수 있어서, 캡션은 절대 재사용(캐싱)하지 않는다.
- 텍스트 레이어가 없는 페이지(스캔본): 페이지를 이미지로 렌더링 후 PaddleTableEngine의
  전체 페이지 OCR(표+일반 텍스트)로 추출

한 PDF 안에 두 종류 페이지가 섞여 있어도 페이지 단위로 자동 판별해서 처리한다.
"""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

from PIL import Image

from ...config import settings
from ...core.document_extractor import BaseDocumentExtractor, ProgressCallback
from ...core.extraction_quality import choose_better_extraction, evaluate_extraction_quality
from ...core.image_captioner import BaseImageCaptioner
from ...core.image_markdown import wrap_image_block
from ...core.pdf_page_classifier import choose_mixed_page_text, classify_pdf_page, rectangle_coverage_ratios
from ...core.table_markdown import rows_to_markdown_table, wrap_table_block
from ...core.table_region_detector import page_likely_has_table
from ..table_extraction.engines.paddle_engine import PaddleTableEngine

logger = logging.getLogger(__name__)


def _bbox_overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    """두 사각형(x0, y0, x1, y1)이 겹치는지 확인한다."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1

# 이보다 작은 이미지(로고, 아이콘, 장식용 구분선 등)는 의미 있는 그림/차트가 아닐 가능성이 높아 건너뛴다.
_MIN_IMAGE_SIDE_PX = 100
# 캡션에 문맥으로 넣을 페이지 텍스트 길이 (너무 길면 프롬프트가 비대해짐)
_CAPTION_CONTEXT_MAX_CHARS = 500
# OCR 모델 언어/전처리 방식이 바뀌면 과거 캐시를 절대 재사용하지 않도록 키에 포함한다.
_OCR_CACHE_VERSION = "v4-korean-pdf-profile"


class PdfExtractor(BaseDocumentExtractor):
    """PDF를 페이지별로 순회하며 디지털/스캔본을 자동 판별해서 텍스트를 뽑아내는 추출기 (BaseDocumentExtractor 구현체)"""

    def __init__(
        self,
        paddle_engine: PaddleTableEngine | None = None,
        image_captioner: BaseImageCaptioner | None = None,
    ) -> None:
        # 스캔본이 없는 PDF만 다룰 경우 PaddleTableEngine 로딩 비용을 피하도록 지연 생성도 가능하게 한다.
        self._paddle_engine = paddle_engine
        self._image_captioner = image_captioner
        self.last_page_diagnostics: list[dict] = []
        self.last_extraction_method = "pdf_mixed"

    async def extract(self, file_path: str, on_progress: ProgressCallback | None = None) -> str:
        """PDF 전체를 순회하며 페이지별 텍스트를 이어붙인 문서 전체 텍스트를 반환한다."""
        import fitz  # PyMuPDF  # type: ignore

        doc = fitz.open(file_path)
        page_texts: list[str] = []
        total_pages = len(doc)
        self.last_page_diagnostics = []

        try:
            for page_index in range(total_pages):
                try:
                    page = doc[page_index]
                    digital_text = page.get_text().strip()
                    image_coverage, max_image_coverage = self._measure_page_image_coverage(page)
                    profile = classify_pdf_page(
                        digital_text,
                        image_coverage_ratio=image_coverage,
                        max_image_coverage_ratio=max_image_coverage,
                        min_digital_chars=settings.pdf_digital_min_chars,
                        min_native_quality=settings.pdf_native_quality_min_score,
                        mixed_image_coverage=settings.pdf_mixed_image_coverage,
                        mixed_max_native_chars=settings.pdf_mixed_max_native_chars,
                    )

                    diagnostic_extra: dict = {"classification": profile.to_dict()}
                    if profile.mode == "digital":
                        method = "digital_text"
                        extracted_text = self._extract_digital_page_text(page, digital_text)
                        logger.info(
                            "페이지 %d: 디지털 텍스트 사용 (%d자, 이미지 점유율 %.1f%%)",
                            page_index + 1,
                            len(digital_text),
                            image_coverage * 100,
                        )
                    elif profile.mode == "ocr":
                        method = "ocr"
                        logger.info(
                            "페이지 %d: OCR 페이지로 판정 (%s)",
                            page_index + 1,
                            "; ".join(profile.reasons),
                        )
                        image = self._render_page_to_image(page)
                        extracted_text = self._ocr_page(image)
                    else:
                        method = "mixed"
                        logger.info(
                            "페이지 %d: 텍스트+이미지 혼합 페이지, OCR 병행 (%s)",
                            page_index + 1,
                            "; ".join(profile.reasons),
                        )
                        image = self._render_page_to_image(page)
                        ocr_text = self._ocr_page(image)
                        extracted_text, merge_strategy = choose_mixed_page_text(digital_text, ocr_text)
                        diagnostic_extra["merge_strategy"] = merge_strategy
                        diagnostic_extra["ocr_quality"] = evaluate_extraction_quality(ocr_text).to_dict()

                    # 디지털/혼합 페이지의 삽화는 원본 이미지 파일도 보존한다. 캡셔닝이 꺼져 있으면
                    # 검색 텍스트에는 추가하지 않으므로 OCR 본문과 중복되지 않는다.
                    image_blocks_text = ""
                    if profile.mode in {"digital", "mixed"}:
                        try:
                            image_blocks_text = await self._extract_page_images(
                                doc, page, page_index + 1, context=extracted_text
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("페이지 %d 이미지 추출 실패(본문은 정상 진행): %s", page_index + 1, exc)
                    page_content = extracted_text + ("\n\n" + image_blocks_text if image_blocks_text else "")
                    page_texts.append(f"<!-- PAGE:{page_index + 1} -->\n{page_content}")
                    self.last_page_diagnostics.append(
                        {
                            "page": page_index + 1,
                            "method": method,
                            **evaluate_extraction_quality(extracted_text).to_dict(),
                            **diagnostic_extra,
                        }
                    )

                    if on_progress is not None:
                        await on_progress(page_index + 1, total_pages)
                except Exception as exc:  # noqa: BLE001
                    # 페이지 하나가 특이한 구조(손상된 이미지, 특수 인코딩 등)라도 문서 전체 추출을
                    # 막지 않는다 — 그 페이지만 건너뛰고 나머지 페이지는 정상적으로 계속 처리한다.
                    logger.warning("페이지 %d 처리 실패, 이 페이지만 건너뜀: %s", page_index + 1, exc)
                    self.last_page_diagnostics.append(
                        {"page": page_index + 1, "method": "error", "score": 0.0, "error": str(exc)}
                    )
        finally:
            doc.close()

        successful_methods = {
            item["method"] for item in self.last_page_diagnostics if item.get("method") != "error"
        }
        if successful_methods and successful_methods == {"digital_text"}:
            self.last_extraction_method = "pdf_text"
        elif successful_methods and successful_methods == {"ocr"}:
            self.last_extraction_method = "pdf_ocr"
        else:
            self.last_extraction_method = "pdf_mixed"

        return "\n\n".join(t for t in page_texts if t.strip())

    @staticmethod
    def _extract_digital_page_text(page, fallback_text: str) -> str:  # noqa: ANN001
        """
        디지털 텍스트 페이지에서 표 격자를 감지해, 표는 TABLE_BLOCK으로 감싸 통째로
        보존하고 나머지 본문은 원래 세로 순서대로 이어붙인다.

        page.get_text()만 쓰면 표의 열 정보가 문자 스트림 순서에 묻혀 사라지고, 청킹
        단계의 "표는 안 쪼갠다" 보호 로직도 TABLE_BLOCK 마커가 없어서 아예 적용되지
        않는다 (표를 일반 본문처럼 취급해서 제목 감지 로직에 걸려 중간이 잘리기도 함).
        find_tables()는 OCR/추측이 아니라 PDF에 그려진 선·좌표만으로 표 격자를 감지하므로
        이 문제를 근본적으로 피할 수 있다.
        """
        if not settings.pdf_native_table_detection_enabled:
            return fallback_text
        try:
            found = page.find_tables()
        except Exception as exc:  # noqa: BLE001 — 표 감지 실패해도 기존 텍스트로 계속 진행
            logger.warning("표 감지 실패, 일반 텍스트로 계속 진행: %s", exc)
            return fallback_text
        if not found.tables:
            return fallback_text

        table_bboxes = [tuple(table.bbox) for table in found.tables]
        segments: list[tuple[float, str]] = []
        for table, bbox in zip(found.tables, table_bboxes):
            rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in table.extract()]
            markdown = rows_to_markdown_table(rows)
            segments.append((bbox[1], wrap_table_block(markdown)))

        for block in page.get_text("blocks"):
            block_bbox = tuple(block[:4])
            text = (block[4] or "").strip()
            if not text:
                continue
            if any(_bbox_overlaps(block_bbox, table_bbox) for table_bbox in table_bboxes):
                continue
            segments.append((block_bbox[1], text))

        segments.sort(key=lambda item: item[0])
        return "\n\n".join(text for _, text in segments)

    @staticmethod
    def _measure_page_image_coverage(page) -> tuple[float, float]:  # noqa: ANN001
        """페이지에 실제 배치된 이미지 사각형의 합집합/최대 단일 점유율을 계산한다."""
        page_rect = page.rect
        rectangles: list[tuple[float, float, float, float]] = []
        for image_info in page.get_images(full=True):
            xref = image_info[0]
            try:
                image_rects = page.get_image_rects(xref)
            except Exception:  # noqa: BLE001 - 손상/특수 inline 이미지 하나는 판정에서 제외
                continue
            for rect in image_rects:
                rectangles.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
        return rectangle_coverage_ratios(
            (float(page_rect.x0), float(page_rect.y0), float(page_rect.x1), float(page_rect.y1)),
            rectangles,
        )

    async def _extract_page_images(self, doc, page, page_number: int, context: str) -> str:  # noqa: ANN001
        """
        페이지에 삽입된 이미지들을 파일로 저장하고, 캡션과 함께 마커 블록 텍스트로 만들어 이어붙인다.
        너무 작은 이미지(로고 등)는 건너뛴다.
        """
        # 캡셔닝이 꺼져 있으면 저장한 이미지가 검색 청크에 연결되지 않는다. 원본 PDF가
        # 보존되어 있어 나중에 캡셔닝을 켜고 다시 추출할 수 있으므로, 수백 페이지의 삽화를
        # 미리 분리 저장하는 불필요한 I/O를 건너뛴다.
        if not settings.pdf_image_captioning_enabled or self._image_captioner is None:
            return ""

        storage_dir = Path(settings.image_storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)

        blocks: list[str] = []
        for image_index, image_info in enumerate(page.get_images(full=True)):
            xref = image_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception as exc:  # noqa: BLE001
                logger.warning("페이지 %d 이미지 %d 추출 실패: %s", page_number, image_index, exc)
                continue

            width, height = base_image.get("width", 0), base_image.get("height", 0)
            if width < _MIN_IMAGE_SIDE_PX or height < _MIN_IMAGE_SIDE_PX:
                continue  # 로고/아이콘/구분선으로 추정되는 작은 이미지는 건너뜀

            image_bytes = base_image["image"]
            image_ext = base_image.get("ext", "png")

            # 파일명을 이미지 내용의 해시로 정해서, 완전히 같은 이미지는 디스크에 한 번만 저장되게 한다
            # (같은 로고/차트가 여러 페이지·여러 문서에 반복돼도 파일 자체는 중복 저장 안 됨).
            image_hash = hashlib.sha256(image_bytes).hexdigest()
            filename = f"{image_hash}.{image_ext}"
            saved_path = storage_dir / filename
            if saved_path.exists():
                logger.info("페이지 %d 이미지 %d: 이미 저장된 이미지 재사용 (%s)", page_number, image_index, filename)
            else:
                saved_path.write_bytes(image_bytes)
                logger.info("페이지 %d 이미지 %d 저장 완료: %s (%dx%d)", page_number, image_index, filename, width, height)

            # 파일은 재사용해도 캡션은 절대 캐싱하지 않는다 — 이 문맥에서 이 이미지가 뭘 나타내는지는
            # 등장할 때마다 다를 수 있어서, 매번 이 페이지의 문맥을 넣어 새로 생성한다.
            caption = await self._caption_image(image_bytes, context=context)
            if not caption:
                # Vision-LLM 캡셔닝이 꺼져있거나 실패해서 진짜 캡션이 없는 경우, "N페이지 이미지 M" 같은
                # 내용 없는 자리표시자로 검색 청크를 만들지 않는다. 예전에 이런 자리표시자 청크가
                # 문서 하나에 수십 개씩 쌓여서, 실제 텍스트 청크를 검색 후보에서 밀어내는 문제가 있었다.
                # 이미지 파일 자체는 이미 디스크에 저장됐으니, 나중에 캡셔닝을 켜면 다시 처리하면 된다.
                logger.info(
                    "페이지 %d 이미지 %d: 캡션 없음(캡셔닝 꺼짐/실패) -> 검색 청크는 생략, 파일만 저장", page_number, image_index
                )
                continue

            # DB/API에서는 storage_dir 기준 상대 경로(=filename)로만 다루고,
            # 실제 파일시스템 절대 경로는 정적 서빙 설정 쪽(main.py)에서 매핑한다.
            blocks.append(wrap_image_block(image_path=filename, caption=caption))

        return "\n\n".join(blocks)

    async def _caption_image(self, image_bytes: bytes, context: str) -> str:
        """이미지 캡션을 생성한다. 캡셔너가 없거나 비활성화면 빈 문자열을 반환한다(기본 캡션으로 대체됨)."""
        if not settings.pdf_image_captioning_enabled or self._image_captioner is None:
            return ""
        image = Image.open(io.BytesIO(image_bytes))
        return await self._image_captioner.caption(image, context=context[:_CAPTION_CONTEXT_MAX_CHARS])

    def _render_page_to_image(self, page) -> Image.Image:  # noqa: ANN001 (fitz.Page 타입은 외부 라이브러리)
        """
        스캔본 페이지를 이미지로 렌더링한다.
        DPI가 높을수록 정확도는 조금 오르지만 처리 시간이 픽셀 수(=DPI 제곱)에 비례해서 늘어난다.
        300->200 DPI로 낮추면 픽셀 수가 약 44%로 줄어 OCR 시간이 크게 준다 (표 구조 인식 자체가
        무거운 게 진짜 병목이라, 해상도를 과하게 높여도 그 부분은 별로 안 빨라짐).
        작은 글씨가 많은 인증서/도면류는 settings.scan_render_dpi를 문서 종류별로 더 높여 쓸 수 있다.
        """
        zoom = settings.scan_render_dpi / 72  # PyMuPDF 기본 72 DPI 기준 배율 계산
        matrix = __import__("fitz").Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        return Image.open(io.BytesIO(pix.tobytes("png")))

    def _ocr_page(self, image: Image.Image) -> str:
        """
        스캔본 페이지 이미지를 OCR해서 텍스트로 변환한다.

        - 먼저 캐시(같은 페이지 이미지+같은 처리방식을 예전에 이미 OCR한 적 있는지)를 확인한다.
        - 표 격자선이 있어 보이는 페이지만 무거운 PPStructureV3(레이아웃+표+수식 분석까지 다 함)로 보내고,
          나머지 일반 텍스트 페이지는 검출+인식만 하는 경량 OCR로 보낸다. 표 없는 페이지가 대부분이라
          이것만으로 전체 처리 시간이 크게 준다.
        """
        if self._paddle_engine is None:
            self._paddle_engine = PaddleTableEngine()

        mode = "full"
        if settings.ocr_table_detection_enabled:
            try:
                mode = "full" if page_likely_has_table(image) else "light"
            except Exception as exc:  # noqa: BLE001
                # 판별 자체가 실패하면 안전하게(정확도 우선) 무거운 경로로 보낸다.
                logger.warning("표 유무 판별 실패, 안전하게 구조화 OCR로 처리: %s", exc)
                mode = "full"

        cached_text = self._read_ocr_cache(image, mode) if settings.ocr_page_cache_enabled else None
        if cached_text is not None:
            logger.info("OCR 캐시 재사용 (mode=%s)", mode)
            return cached_text

        primary_text = (
            self._paddle_engine.extract_full_page_text(image)
            if mode == "full"
            else self._paddle_engine.extract_light_text(image)
        )

        primary_quality = evaluate_extraction_quality(primary_text)
        text = primary_text
        if primary_quality.score < settings.ocr_fallback_min_score:
            fallback_mode = "light" if mode == "full" else "full"
            logger.warning(
                "OCR 1차 결과 품질 낮음(mode=%s, score=%.3f) -> %s 경로 재시도",
                mode,
                primary_quality.score,
                fallback_mode,
            )
            fallback_cached = self._read_ocr_cache(image, fallback_mode) if settings.ocr_page_cache_enabled else None
            fallback_text = fallback_cached
            if fallback_text is None:
                fallback_text = (
                    self._paddle_engine.extract_light_text(image)
                    if fallback_mode == "light"
                    else self._paddle_engine.extract_full_page_text(image)
                )
                if settings.ocr_page_cache_enabled:
                    self._write_ocr_cache(image, fallback_mode, fallback_text)
            text, selected_quality, selected = choose_better_extraction(primary_text, fallback_text)
            logger.info(
                "OCR 경로 비교 완료: primary=%s(%.3f), fallback=%s(%.3f) -> %s 선택",
                mode,
                primary_quality.score,
                fallback_mode,
                evaluate_extraction_quality(fallback_text).score,
                selected,
            )
            primary_quality = selected_quality

        if settings.ocr_page_cache_enabled:
            self._write_ocr_cache(image, mode, text)

        return text

    @staticmethod
    def _ocr_cache_path(image: Image.Image, mode: str) -> Path:
        """캐시 키 = 렌더링된 페이지 이미지 내용의 해시 + 처리방식(light/full).
        같은 파일을 재업로드해도, 같은 DPI로 렌더링하면 이미지 바이트가 동일해서 같은 키로 잡힌다."""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_hash = hashlib.sha256(buffer.getvalue()).hexdigest()
        cache_dir = Path(settings.ocr_cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{image_hash}_{_OCR_CACHE_VERSION}_{mode}.txt"

    def _read_ocr_cache(self, image: Image.Image, mode: str) -> str | None:
        path = self._ocr_cache_path(image, mode)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _write_ocr_cache(self, image: Image.Image, mode: str, text: str) -> None:
        path = self._ocr_cache_path(image, mode)
        path.write_text(text, encoding="utf-8")
