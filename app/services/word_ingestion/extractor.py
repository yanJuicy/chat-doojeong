"""
Word(.docx) 문서에서 텍스트를 추출한다.
문단과 표가 원문 순서 그대로 섞여 있을 수 있어서, python-docx의 저수준 XML을 순회하며
"이 자리에 표가 있었다"는 순서를 그대로 보존한다 (표가 통째로 뒤로 밀리는 문제 방지).
"""
from __future__ import annotations

import logging

from ...core.document_extractor import BaseDocumentExtractor
from ...core.table_markdown import rows_to_markdown_table, wrap_table_block

logger = logging.getLogger(__name__)

class WordExtractor(BaseDocumentExtractor):
    """python-docx 기반 .docx 추출기 (BaseDocumentExtractor 구현체)"""

    async def extract(self, file_path: str, on_progress=None) -> str:  # noqa: ANN001 (선택 진행률 콜백, 이 추출기는 사용 안 함)
        """문서 전체를 문단/표 원문 순서대로 순회하며 텍스트로 변환한다."""
        from docx import Document as DocxDocument  # type: ignore

        doc = DocxDocument(file_path)
        parts: list[str] = []

        for block in self._iter_block_items(doc):
            if block["type"] == "paragraph":
                text = block["text"].strip()
                if text:
                    parts.append(text)
            elif block["type"] == "table":
                markdown_table = rows_to_markdown_table(block["rows"])
                parts.append(wrap_table_block(markdown_table))

        return "\n\n".join(parts)

    @staticmethod
    def _iter_block_items(doc) -> list[dict]:  # noqa: ANN001
        """
        문서 본문(body)의 자식 요소를 원문 순서대로 순회하며,
        문단은 {"type": "paragraph", "text": ...}, 표는 {"type": "table", "rows": [[...]]} 로 변환한다.
        python-docx는 문단/표를 순서 보존해서 한 번에 순회하는 고수준 API를 제공하지 않아서
        XML 트리를 직접 순회하는 방식(공식적으로 알려진 우회 패턴)을 쓴다.
        """
        from docx.oxml.table import CT_Tbl  # type: ignore
        from docx.oxml.text.paragraph import CT_P  # type: ignore
        from docx.table import Table  # type: ignore
        from docx.text.paragraph import Paragraph  # type: ignore

        items: list[dict] = []
        for child in doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraph = Paragraph(child, doc)
                items.append({"type": "paragraph", "text": paragraph.text})
            elif isinstance(child, CT_Tbl):
                table = Table(child, doc)
                rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
                items.append({"type": "table", "rows": rows})
        return items
