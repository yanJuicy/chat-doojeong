"""
PDF 페이지를 표/OCR 처리용 이미지로 렌더링하는 공용 유틸리티.

일반 RAG 문서 추출(app/services/pdf_ingestion/extractor.py)과 주간보고서 업로드
(app/backend/work_reports.py)가 스캔 페이지를 다루는 방식(find_tables()/PaddleOCR로 표를
뽑는 것)은 서로 다르지만, "페이지를 이미지로 렌더링하는" 이 한 단계만은 완전히 동일한 코드였다.
표 추출 흐름 자체는 두 경로가 요구사항이 달라서(근사검색용 vs 보고서 정확 재구성용) 계속
분리해서 유지하되, 진짜 중복이던 이 부분만 공용화한다.
"""
from __future__ import annotations

import io

from PIL import Image


def render_page_to_image(page, dpi: int) -> Image.Image:  # noqa: ANN001 — fitz.Page는 외부 라이브러리 타입
    """PDF 페이지를 지정한 DPI의 이미지로 렌더링한다.

    DPI가 높을수록 정확도는 조금 오르지만 처리 시간이 픽셀 수(=DPI 제곱)에 비례해서 늘어난다
    (표 구조 인식 자체가 무거운 게 진짜 병목이라, 해상도를 과하게 높여도 그 부분은 별로 안 빨라짐).
    """
    import fitz  # PyMuPDF

    zoom = dpi / 72  # PyMuPDF 기본 72 DPI 기준 배율 계산
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    return Image.open(io.BytesIO(pix.tobytes("png")))
