"""일반 텍스트(.txt, .md) 파일 추출기 - 인코딩 자동 판별해서 그대로 읽는다."""
from __future__ import annotations

from .document_extractor import BaseDocumentExtractor


class PlainTextExtractor(BaseDocumentExtractor):
    """.txt/.md 파일을 그대로 읽어들이는 추출기 (OCR/파싱 불필요)"""

    async def extract(self, file_path: str, on_progress=None) -> str:  # noqa: ANN001 (선택 진행률 콜백, 이 추출기는 사용 안 함)
        for encoding in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with open(file_path, encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        raise ValueError(f"지원하는 인코딩(utf-8, cp949)으로 읽을 수 없습니다: {file_path}")
