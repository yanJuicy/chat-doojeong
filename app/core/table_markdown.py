"""여러 추출기(Word, HTML 등)가 공용으로 쓰는 표 -> Markdown 변환 유틸."""
from __future__ import annotations

TABLE_START_MARKER = "<!-- TABLE_BLOCK_START -->"
TABLE_END_MARKER = "<!-- TABLE_BLOCK_END -->"


def rows_to_markdown_table(rows: list[list[str]]) -> str:
    """2차원 문자열 리스트(표의 행/열)를 Markdown 표 문자열로 변환한다."""
    if not rows:
        return ""

    n_cols = max(len(r) for r in rows)
    lines = []
    header = rows[0] + [""] * (n_cols - len(rows[0]))
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * n_cols) + " |")
    for row in rows[1:]:
        padded = row + [""] * (n_cols - len(row))
        lines.append("| " + " | ".join(padded) + " |")

    return "\n".join(lines)


def wrap_table_block(markdown_table: str) -> str:
    """Markdown 표 문자열을 청크 마커로 감싼다 (청킹 단계에서 표 내부를 자르지 않도록)."""
    return f"{TABLE_START_MARKER}\n{markdown_table}\n{TABLE_END_MARKER}"
