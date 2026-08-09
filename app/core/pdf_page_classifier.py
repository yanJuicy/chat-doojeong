"""PDF 페이지를 디지털 텍스트/스캔/OCR 혼합 페이지로 판정하는 순수 로직."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Literal

from .extraction_quality import ExtractionQuality, evaluate_extraction_quality
from .text_garble_detector import is_text_garbled

PageMode = Literal["digital", "ocr", "mixed"]
_LINE_KEY = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)


@dataclass(frozen=True)
class PdfPageProfile:
    mode: PageMode
    native_text_chars: int
    native_quality: ExtractionQuality
    image_coverage_ratio: float
    max_image_coverage_ratio: float
    is_garbled: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["native_quality"] = self.native_quality.to_dict()
        return data


def classify_pdf_page(
    native_text: str,
    *,
    image_coverage_ratio: float,
    max_image_coverage_ratio: float,
    min_digital_chars: int = 20,
    min_native_quality: float = 0.20,
    mixed_image_coverage: float = 0.55,
    mixed_max_native_chars: int = 400,
) -> PdfPageProfile:
    """텍스트 품질과 이미지 면적을 함께 사용해 페이지 처리 방식을 결정한다."""
    text = (native_text or "").strip()
    quality = evaluate_extraction_quality(text)
    garbled = bool(text) and is_text_garbled(text)
    image_coverage = _clamp_ratio(image_coverage_ratio)
    max_image_coverage = _clamp_ratio(max_image_coverage_ratio)
    dominant_image = image_coverage >= mixed_image_coverage or max_image_coverage >= mixed_image_coverage
    reasons: list[str] = []

    if garbled:
        reasons.append("네이티브 텍스트의 한글 폰트 인코딩이 깨진 것으로 판단")
        return PdfPageProfile(
            "ocr", len(text), quality, image_coverage, max_image_coverage, True, reasons
        )

    if not text:
        reasons.append("추출 가능한 네이티브 텍스트가 없음")
        if dominant_image:
            reasons.append("큰 이미지가 페이지 본문을 차지함")
        return PdfPageProfile(
            "ocr", 0, quality, image_coverage, max_image_coverage, False, reasons
        )

    # 제목 몇 글자만 텍스트이고 본문은 큰 이미지인 디자인 PDF를 잡는다.
    if dominant_image and len(text) <= mixed_max_native_chars:
        reasons.append("네이티브 텍스트와 큰 본문 이미지가 함께 존재")
        reasons.append("이미지 내부 텍스트 누락 방지를 위해 OCR 병행")
        return PdfPageProfile(
            "mixed", len(text), quality, image_coverage, max_image_coverage, False, reasons
        )

    if len(text) < min_digital_chars:
        # 작은 로고/장식 이미지도 없고 짧지만 정상적인 제목만 있는 페이지는 OCR할 이유가 없다.
        if image_coverage < 0.15 and quality.content_char_ratio >= 0.45:
            reasons.append("짧지만 읽을 수 있는 네이티브 텍스트이며 큰 이미지가 없음")
            return PdfPageProfile(
                "digital", len(text), quality, image_coverage, max_image_coverage, False, reasons
            )
        reasons.append(f"네이티브 텍스트가 기준보다 짧음({len(text)} < {min_digital_chars})")
        return PdfPageProfile(
            "ocr", len(text), quality, image_coverage, max_image_coverage, False, reasons
        )

    if quality.score < min_native_quality:
        reasons.append(
            f"네이티브 텍스트 품질이 기준 미달({quality.score:.3f} < {min_native_quality:.3f})"
        )
        return PdfPageProfile(
            "ocr", len(text), quality, image_coverage, max_image_coverage, False, reasons
        )

    reasons.append("충분하고 읽을 수 있는 네이티브 텍스트")
    return PdfPageProfile(
        "digital", len(text), quality, image_coverage, max_image_coverage, False, reasons
    )


def choose_mixed_page_text(native_text: str, ocr_text: str) -> tuple[str, str]:
    """혼합 페이지의 두 결과에서 누락은 줄이고 중복은 억제한다.

    OCR이 네이티브 텍스트보다 훨씬 많은 본문을 복원하면 OCR 결과를 사용한다. 두 결과가
    서로 보완적이면 줄 단위로 합치며, 거의 같은 줄은 유사도 비교로 한 번만 남긴다.
    """
    native = (native_text or "").strip()
    ocr = (ocr_text or "").strip()
    if not native:
        return ocr, "ocr_only"
    if not ocr:
        return native, "native_only"

    native_quality = evaluate_extraction_quality(native)
    ocr_quality = evaluate_extraction_quality(ocr)
    if len(ocr) >= max(int(len(native) * 1.35), len(native) + 40) and ocr_quality.score >= native_quality.score - 0.10:
        return ocr, "ocr_richer"
    if len(native) >= max(int(len(ocr) * 1.50), len(ocr) + 100) and native_quality.score >= ocr_quality.score:
        return native, "native_richer"

    merged_lines = [line.strip() for line in native.splitlines() if line.strip()]
    existing_keys = [_line_key(line) for line in merged_lines]
    for line in (line.strip() for line in ocr.splitlines() if line.strip()):
        key = _line_key(line)
        if not key:
            continue
        if any(_same_line(key, existing) for existing in existing_keys if existing):
            continue
        merged_lines.append(line)
        existing_keys.append(key)
    return "\n".join(merged_lines), "merged"


def _same_line(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) >= 10 and (left in right or right in left):
        return True
    if min(len(left), len(right)) < 8:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.88


def _line_key(value: str) -> str:
    return _LINE_KEY.sub("", value.casefold())


def _clamp_ratio(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def rectangle_union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    """겹치는 이미지 사각형을 중복 계산하지 않고 합집합 면적을 구한다."""
    if not rectangles:
        return 0.0
    x_points = sorted({coordinate for x0, _, x1, _ in rectangles for coordinate in (x0, x1)})
    area = 0.0
    for left, right in zip(x_points, x_points[1:]):
        if right <= left:
            continue
        midpoint = (left + right) / 2
        intervals = sorted(
            (y0, y1) for x0, y0, x1, y1 in rectangles if x0 <= midpoint < x1
        )
        if not intervals:
            continue
        covered_y = 0.0
        current_start, current_end = intervals[0]
        for start, end in intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                covered_y += current_end - current_start
                current_start, current_end = start, end
        covered_y += current_end - current_start
        area += (right - left) * covered_y
    return area


def rectangle_coverage_ratios(
    page_rectangle: tuple[float, float, float, float],
    rectangles: list[tuple[float, float, float, float]],
) -> tuple[float, float]:
    """페이지 경계 안에서 이미지 합집합/최대 단일 이미지 점유율을 반환한다."""
    page_x0, page_y0, page_x1, page_y1 = page_rectangle
    page_area = max((page_x1 - page_x0) * (page_y1 - page_y0), 1.0)
    clipped: set[tuple[float, float, float, float]] = set()
    for x0, y0, x1, y1 in rectangles:
        bounded = (
            max(float(x0), page_x0),
            max(float(y0), page_y0),
            min(float(x1), page_x1),
            min(float(y1), page_y1),
        )
        if bounded[2] > bounded[0] and bounded[3] > bounded[1]:
            clipped.add(bounded)
    if not clipped:
        return 0.0, 0.0
    union_ratio = min(rectangle_union_area(list(clipped)) / page_area, 1.0)
    max_ratio = min(max((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in clipped) / page_area, 1.0)
    return round(union_ratio, 4), round(max_ratio, 4)
