"""
표 추출 결과의 구조적 신뢰도를 계산한다.

PP-StructureV3(Markdown 변환)는 병합 셀 정보를 정확히 못 살리는 경우가 있어서,
행마다 열 개수가 들쭉날쭉해지는 게 "표가 깨졌다"는 가장 흔한 신호다.
이걸 결론(신뢰함/의심함)만 내지 않고, 항상 퍼센트(일관성 비율)로 보여준다.
"""
from __future__ import annotations

import re


def compute_table_confidence(markdown_table: str) -> dict:
    """
    Markdown 표 문자열을 받아 행별 열 개수 일관성 비율을 계산한다.

    Returns:
        {"confidence": 0.0~1.0, "n_rows": int, "n_cols_header": int, "inconsistent_rows": [행 번호, ...]}
    """
    lines = [line for line in markdown_table.strip().split("\n") if line.strip().startswith("|")]
    # 구분선(|---|---|) 행은 제외
    data_lines = [line for line in lines if not re.match(r"^\s*\|[\s:|-]+\|\s*$", line)]

    if not data_lines:
        return {"confidence": 0.0, "n_rows": 0, "n_cols_header": 0, "inconsistent_rows": []}

    def count_cols(line: str) -> int:
        return len(line.strip().strip("|").split("|"))

    header_cols = count_cols(data_lines[0])
    inconsistent_rows = [i for i, line in enumerate(data_lines) if count_cols(line) != header_cols]

    consistency_ratio = 1.0 - (len(inconsistent_rows) / len(data_lines))

    return {
        "confidence": round(consistency_ratio, 4),
        "n_rows": len(data_lines),
        "n_cols_header": header_cols,
        "inconsistent_rows": inconsistent_rows,
    }
