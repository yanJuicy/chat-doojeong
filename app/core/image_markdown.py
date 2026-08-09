"""
이미지(그림/차트) 블록 마커 유틸.

원리는 표 마커(TABLE_BLOCK_START/END)와 동일하다: 문서 원문 텍스트 안에
"여기에 이미지가 있었다"는 표시를 남겨서, 청킹 단계에서 이 블록이 잘리지 않고
캡션+이미지 경로가 하나의 청크로 통째로 유지되도록 한다.

형식:
  <!-- IMAGE_BLOCK_START path="images/xxx.png" -->
  (이미지 캡션 텍스트 — Vision-LLM이 생성하거나, 없으면 기본 문구)
  <!-- IMAGE_BLOCK_END -->
"""
from __future__ import annotations

import re

_IMAGE_BLOCK_PATTERN = re.compile(
    r'<!-- IMAGE_BLOCK_START path="(?P<path>[^"]+)" -->\n?(?P<caption>.*?)<!-- IMAGE_BLOCK_END -->',
    re.DOTALL,
)


def wrap_image_block(image_path: str, caption: str) -> str:
    """이미지 경로+캡션을 마커로 감싼 블록 문자열로 만든다."""
    return f'<!-- IMAGE_BLOCK_START path="{image_path}" -->\n{caption}\n<!-- IMAGE_BLOCK_END -->'


def find_image_blocks(text: str) -> list[tuple[str, str]]:
    """텍스트 안의 모든 이미지 블록을 찾아 (image_path, caption) 목록으로 반환한다."""
    return [(m.group("path"), m.group("caption").strip()) for m in _IMAGE_BLOCK_PATTERN.finditer(text)]


def strip_image_blocks(text: str, placeholder: str) -> str:
    """이미지 블록을 자리표시자로 치환한 텍스트를 반환한다 (원본은 안 건드림)."""
    return _IMAGE_BLOCK_PATTERN.sub(placeholder, text)
