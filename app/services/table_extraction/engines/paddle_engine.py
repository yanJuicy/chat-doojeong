"""
PaddleOCR 3.x의 PPStructureV3 파이프라인 기반 표/텍스트 통합 OCR 엔진.

PaddleOCR 2.x의 PPStructure 클래스는 3.x에서 완전히 제거되고 PPStructureV3로 대체되었다.
PPStructureV3는 페이지 전체를 분석해 Markdown으로 결과를 뽑아주는 방식이라,
표는 Markdown 표 구문으로, 일반 텍스트는 그대로 섞여서 나온다.
그래서 이 구현은 "표 영역만 따로 파싱"하는 대신, 결과 Markdown에서
표처럼 보이는 줄 뭉치를 찾아 청크 마커로 감싸는 방식을 쓴다.
"""
from __future__ import annotations

import logging
import re

import numpy as np
from PIL import Image

from ....core.table_markdown import TABLE_END_MARKER, TABLE_START_MARKER
from ..interfaces import BaseTableEngine
from ..models import ExtractionSource, TableBlock, TableCell

logger = logging.getLogger(__name__)

# Markdown 표의 한 행으로 보이는 패턴 ("| ... | ... |")
_MD_TABLE_ROW_PATTERN = re.compile(r"^\s*\|.*\|\s*$")


class PaddleTableEngine(BaseTableEngine):
    """PPStructureV3 기반 표+텍스트 통합 인식 엔진 (+경량 텍스트 전용 OCR 병행 지원)"""

    def __init__(self) -> None:
        self._pipeline = None  # PPStructureV3 (무거움) - 표가 있어 보이는 페이지에만 씀, 지연 초기화
        self._light_ocr = None  # 텍스트 전용 PaddleOCR (가벼움) - 나머지 페이지, 지연 초기화

    def _ensure_pipeline(self) -> None:
        """PPStructureV3(무거운 전체 분석)를 필요할 때만 초기화한다."""
        if self._pipeline is not None:
            return
        try:
            from paddleocr import PPStructureV3  # type: ignore

            init_kwargs = {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                # PaddleOCR 3.x는 lang을 생략하면 영문 모델을 선택한다. 한글 문서에서
                # 글자가 통째로 사라지거나 CO2 같은 영문/숫자만 남는 원인이 된다.
                "lang": "korean",
            }
            # 주의: paddlepaddle-gpu가 아닌 CPU 전용 빌드에서 device="gpu:*"를 지정하면
            # 에러 대신 무한 대기(hang)로 이어지는 경우가 있어, GPU 빌드가 확인되기 전까지는
            # settings.paddle_use_gpu 값과 무관하게 항상 cpu로 고정한다.
            # TODO: paddlepaddle-gpu 설치 후 settings.paddle_use_gpu 기반 분기로 되돌릴 것
            device = "cpu"
            logger.info("PPStructureV3 파이프라인 초기화 시작 (device=%s) — 첫 실행 시 다소 걸릴 수 있음", device)
            try:
                self._pipeline = PPStructureV3(device=device, **init_kwargs)
            except TypeError:
                # 설치된 버전에 따라 device 인자명이 다를 수 있어, 실패 시 기본값으로 재시도한다.
                logger.warning("PPStructureV3에 device 인자를 전달하지 못해 기본 설정으로 재시도합니다.")
                self._pipeline = PPStructureV3(**init_kwargs)
            logger.info("PPStructureV3 파이프라인 초기화 완료")
        except ImportError:
            logger.warning("paddleocr 패키지가 설치되어 있지 않습니다. requirements.txt를 확인하세요.")

    def _ensure_light_ocr(self) -> None:
        """
        표/레이아웃/수식 분석 없이 텍스트 검출+인식만 하는 경량 엔진을 초기화한다.
        PPStructureV3는 문서 레이아웃 분석, 표 분류, 표 구조 인식(셀 검출 2종), 수식 인식까지
        모델을 여러 개 태우는데, 표가 없는 일반 텍스트 페이지엔 이 중 대부분이 낭비다.
        """
        if self._light_ocr is not None:
            return
        try:
            from paddleocr import PaddleOCR  # type: ignore

            logger.info("경량 텍스트 OCR(PaddleOCR) 초기화 시작")
            try:
                self._light_ocr = PaddleOCR(
                    device="cpu",
                    lang="korean",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            except TypeError:
                self._light_ocr = PaddleOCR(use_angle_cls=False, lang="korean")
            logger.info("경량 텍스트 OCR 초기화 완료")
        except ImportError:
            logger.warning("paddleocr 패키지가 설치되어 있지 않습니다.")

    async def extract(self, image: Image.Image, page_number: int) -> list[TableBlock]:
        """이미지에서 표로 보이는 Markdown 블록을 찾아 TableBlock 목록으로 변환한다 (간이 파싱)."""
        markdown_text = self._run_and_get_markdown(image)
        table_markdown_blocks = self._extract_markdown_table_blocks(markdown_text)

        tables: list[TableBlock] = []
        for md_table in table_markdown_blocks:
            cells, n_rows, n_cols = self._parse_markdown_table(md_table)
            tables.append(
                TableBlock(
                    page_number=page_number,
                    bbox=(0.0, 0.0, float(image.width), float(image.height)),
                    cells=cells,
                    n_rows=n_rows,
                    n_cols=n_cols,
                    confidence=1.0,  # PPStructureV3는 표 단위 confidence를 별도로 노출하지 않음
                    source=ExtractionSource.PADDLE_STRUCTURE,
                    html=None,
                )
            )
        return tables

    def extract_full_page_text(self, image: Image.Image) -> str:
        """
        스캔본 페이지 전체를 OCR한다 (항상 무거운 PPStructureV3 경로 — 표 추출이 명시적으로 필요할 때).
        표는 Markdown 표 그대로 두되 청크 마커로 감싸고, 나머지 텍스트는 그대로 이어붙인다.
        """
        markdown_text = self._run_and_get_markdown(image)
        return self._wrap_table_blocks_with_markers(markdown_text)

    def extract_light_text(self, image: Image.Image) -> str:
        """
        표가 없을 것으로 판단된 페이지용 — 텍스트 검출+인식만 하는 가벼운 경로.
        레이아웃 분석, 표 분류/구조 인식, 수식 인식 모델을 전부 건너뛰어서 훨씬 빠르다.
        """
        self._ensure_light_ocr()
        if self._light_ocr is None:
            raise RuntimeError("경량 OCR 엔진이 초기화되지 않았습니다.")

        img_array = np.array(image.convert("RGB"))
        results = list(self._light_ocr.predict(input=img_array))
        if not results:
            return ""

        lines: list[str] = []
        for res in results:
            texts = res.get("rec_texts") if isinstance(res, dict) else getattr(res, "rec_texts", None)
            if texts:
                lines.extend(str(t) for t in texts)
        return "\n".join(lines)

    def _run_and_get_markdown(self, image: Image.Image) -> str:
        """PPStructureV3로 이미지 한 장을 분석해 Markdown 텍스트를 반환한다."""
        self._ensure_pipeline()
        if self._pipeline is None:
            raise RuntimeError("PaddleTableEngine이 초기화되지 않았습니다.")

        img_array = np.array(image.convert("RGB"))
        results = list(self._pipeline.predict(input=img_array))
        if not results:
            return ""

        md_infos = [res.markdown for res in results]
        concatenated = self._pipeline.concatenate_markdown_pages(md_infos)
        return self._coerce_to_text(concatenated)

    @staticmethod
    def _coerce_to_text(markdown_result) -> str:  # noqa: ANN001
        """
        concatenate_markdown_pages()의 반환값(MarkdownResult 등 커스텀 객체일 수 있음)에서
        실제 Markdown 문자열을 최대한 안전하게 뽑아낸다.
        """
        if isinstance(markdown_result, str):
            return markdown_result

        # dict-like 접근 (get 메서드 지원 여부 확인)
        if hasattr(markdown_result, "get"):
            for key in ("markdown_texts", "markdown_text", "text", "content"):
                value = markdown_result.get(key)
                if isinstance(value, str):
                    return value

        # 속성 접근
        for attr in ("markdown_texts", "markdown_text", "text", "content"):
            value = getattr(markdown_result, attr, None)
            if isinstance(value, str):
                return value

        logger.warning(
            "MarkdownResult에서 텍스트를 추출하지 못해 str() 변환으로 대체합니다. 사용 가능한 속성: %s",
            [a for a in dir(markdown_result) if not a.startswith("_")],
        )
        return str(markdown_result)

    @staticmethod
    def _extract_markdown_table_blocks(markdown_text: str) -> list[str]:
        """Markdown 텍스트에서 표로 보이는 연속된 줄 뭉치만 추출한다."""
        lines = markdown_text.split("\n")
        blocks: list[str] = []
        current: list[str] = []

        for line in lines:
            if _MD_TABLE_ROW_PATTERN.match(line):
                current.append(line)
            else:
                if current:
                    blocks.append("\n".join(current))
                    current = []
        if current:
            blocks.append("\n".join(current))

        return blocks

    @staticmethod
    def _wrap_table_blocks_with_markers(markdown_text: str) -> str:
        """Markdown 텍스트 내 표 블록마다 청크 마커를 삽입한다."""
        lines = markdown_text.split("\n")
        output_lines: list[str] = []
        in_table = False

        for line in lines:
            is_table_row = bool(_MD_TABLE_ROW_PATTERN.match(line))
            if is_table_row and not in_table:
                output_lines.append(TABLE_START_MARKER)
                in_table = True
            elif not is_table_row and in_table:
                output_lines.append(TABLE_END_MARKER)
                in_table = False
            output_lines.append(line)

        if in_table:
            output_lines.append(TABLE_END_MARKER)

        return "\n".join(output_lines)

    @staticmethod
    def _parse_markdown_table(md_table: str) -> tuple[list[TableCell], int, int]:
        """Markdown 표 문자열을 셀 리스트로 파싱한다 (병합 셀은 지원하지 않는 간이 파서)."""
        rows = [line for line in md_table.split("\n") if line.strip()]
        # 구분선(|---|---|) 행은 셀 데이터가 아니므로 제외한다.
        data_rows = [r for r in rows if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)]

        cells: list[TableCell] = []
        max_col = 0
        for row_idx, row in enumerate(data_rows):
            col_values = [c.strip() for c in row.strip().strip("|").split("|")]
            for col_idx, text in enumerate(col_values):
                cells.append(TableCell(row=row_idx, col=col_idx, text=text))
            max_col = max(max_col, len(col_values))

        return cells, len(data_rows), max_col
