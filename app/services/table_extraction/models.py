"""
표 추출 파이프라인에서 사용하는 Pydantic 데이터 모델.
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class ExtractionSource(str, Enum):
    """표 데이터를 어떤 엔진으로 추출했는지 표시"""

    PADDLE_STRUCTURE = "paddle_structure"


class TableCell(BaseModel):
    """표의 개별 셀"""

    row: int = Field(..., description="0부터 시작하는 행 인덱스")
    col: int = Field(..., description="0부터 시작하는 열 인덱스")
    row_span: int = Field(default=1, description="병합된 행 개수")
    col_span: int = Field(default=1, description="병합된 열 개수")
    text: str = Field(default="", description="셀 내부 텍스트")


class TableBlock(BaseModel):
    """페이지 내 표 하나에 대한 추출 결과"""

    page_number: int
    bbox: tuple[float, float, float, float] = Field(..., description="표 영역 좌표 (x0, y0, x1, y1)")
    cells: list[TableCell] = Field(default_factory=list)
    n_rows: int
    n_cols: int
    confidence: float = Field(..., ge=0.0, le=1.0, description="구조 인식 신뢰도")
    source: ExtractionSource
    markdown: str | None = Field(default=None, description="Markdown 표")
