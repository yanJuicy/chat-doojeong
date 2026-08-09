"""
저장된 HTML 파일(크롤러가 받아온 결과)에서 본문 텍스트를 추출한다.

- 네비게이션/광고/스크립트 등 본문과 무관한 태그는 제거한다.
- <table> 태그는 Markdown 표로 변환해서 청크 마커로 감싼다 (다른 추출기들과 동일한 규약).
"""
from __future__ import annotations

from ...core.document_extractor import BaseDocumentExtractor
from ...core.table_markdown import rows_to_markdown_table, wrap_table_block

_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "noscript", "form", "iframe"]


class HtmlExtractor(BaseDocumentExtractor):
    """저장된 .html 파일에서 본문 텍스트+표를 추출하는 추출기 (BaseDocumentExtractor 구현체)"""

    async def extract(self, file_path: str, on_progress=None) -> str:  # noqa: ANN001 (선택 진행률 콜백, 이 추출기는 사용 안 함)
        from bs4 import BeautifulSoup  # type: ignore

        with open(file_path, encoding="utf-8", errors="ignore") as f:
            html = f.read()

        soup = BeautifulSoup(html, "html.parser")

        for tag_name in _NOISE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # <table>은 미리 Markdown으로 변환해서 원래 자리에 되돌려 넣는다 (문단 순서 보존)
        for table_tag in soup.find_all("table"):
            rows = [
                [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
                for row in table_tag.find_all("tr")
            ]
            rows = [r for r in rows if r]  # 빈 행 제거
            if rows:
                markdown_table = rows_to_markdown_table(rows)
                table_tag.replace_with(f"\n\n{wrap_table_block(markdown_table)}\n\n")
            else:
                table_tag.decompose()

        body = soup.find("main") or soup.find("article") or soup.body or soup
        text = body.get_text(separator="\n")

        # 연속 빈 줄 정리 (HTML 특성상 공백이 많이 남음)
        lines = [line.strip() for line in text.split("\n")]
        cleaned = "\n".join(line for line in lines if line)

        return cleaned
