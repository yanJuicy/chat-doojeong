"""
구조 기반(제목/섹션) 청킹 구현체.

매뉴얼·가이드처럼 "1. 설치 > 1.1 요구사항" 식으로 구조가 뚜렷한 문서에 적합하다.
의미기반 청킹(SemanticChunker)은 인접 문장 유사도만 보다 보니, 절차 단계나 섹션 경계를
무시하고 문장 중간에서 잘라버리는 경우가 있다 — 이 청커는 구조를 먼저 존중해서 그 문제를 피한다.

동작 방식:
  1. 표/이미지 블록은 SemanticChunker와 동일한 규칙으로 먼저 뽑아내 통째로 하나의 청크로 만든다.
  2. 나머지 본문에서 제목처럼 보이는 줄(마크다운 #, 번호 매기기 "1.", "1.1" 등)을 찾아 섹션 경계로 삼는다.
     단, "1. 프로그램을 종료한다."처럼 완결된 문장(절차 단계)은 제목으로 오인하지 않는다
     (제목 후보 길이 + 한국어 문장 종결 어미 여부로 구분).
  3. 제목이 거의 없는 문서(구조가 안 뚜렷한 일반 산문)는 SemanticChunker에게 그대로 위임한다.
  4. 섹션 하나가 너무 크면(max_tokens 초과) 그 섹션 안에서만 의미기반으로 추가 분할한다
     (SemanticChunker의 문장 분할 로직을 재사용).
  5. 너무 작은 연속 섹션은 인접한 것과 합쳐서 청크 수가 쓸데없이 많아지는 걸 막는다.
  6. 청크 본문 앞에 "[섹션: 1. 설치 > 1.2 설치 절차]"처럼 상위 제목 경로를 붙여서,
     청크만 봐도 어느 섹션 소속인지 알 수 있게 한다 (검색/답변 근거 추적에 도움).
"""
from __future__ import annotations

import logging
import re
import uuid

from ..config import settings
from .chunking import BaseChunker, Chunk
from .embeddings import BaseEmbeddingProvider
from .image_markdown import find_image_blocks, strip_image_blocks
from .intent_classifier import INTENT_SECTION_KEYWORDS
from .semantic_chunker import SemanticChunker
from .table_markdown import TABLE_END_MARKER, TABLE_START_MARKER

logger = logging.getLogger(__name__)

_TABLE_BLOCK_PATTERN = re.compile(re.escape(TABLE_START_MARKER) + r"(.*?)" + re.escape(TABLE_END_MARKER), re.DOTALL)
_TABLE_PLACEHOLDER = "\uE000TABLE_PLACEHOLDER\uE000"
_IMAGE_PLACEHOLDER = "\uE001IMAGE_PLACEHOLDER\uE001"
_PAGE_BLOCK_PATTERN = re.compile(r"<!-- PAGE:(\d+) -->\s*(.*?)(?=<!-- PAGE:\d+ -->|\Z)", re.DOTALL)

# 제목 후보 패턴: 마크다운(# ~ ######) 또는 번호 매기기(1., 1.1, 1.1.2 등)로 시작하는 줄
_HEADING_PATTERN = re.compile(r"^(?:#{1,6}\s+|\d+(?:\.\d+)*\.?\s+)(\S.*)$")
_ALL_CAPS_HEADING_PATTERN = re.compile(r"^[A-Z][A-Z0-9 /&+_-]{2,39}$")
# 한국어 문장 종결 어미로 끝나면 "제목"이 아니라 "완결된 문장(절차 단계 등)"일 가능성이 높다.
_SENTENCE_ENDING_PATTERN = re.compile(r"(다|요|음|함|니다)[.!?]?\s*$")
# 제목치고 너무 길면(=문장일 가능성) 제외한다.
_MAX_HEADING_TITLE_CHARS = 40
# 이 개수 미만으로 제목이 발견되면 "구조가 뚜렷한 문서"로 안 보고 의미기반 청킹에 위임한다.
_MIN_HEADINGS_TO_TRIGGER = 2
# 이 토큰 수 미만인 연속 섹션은 인접 섹션과 합친다 (너무 잘게 쪼개지는 것 방지).
_MIN_MERGE_TOKENS = 100


# 번호/마크다운 제목이 아니어도, 이 도메인 키워드가 짧은 독립 행으로 등장하면 제목 후보로 본다
# (예: "설치 방법", "안전 및 주의사항" 처럼 번호 없이 소제목만 던지는 매뉴얼 스타일 대응).
_ALL_SECTION_KEYWORDS = sorted(
    {kw for keywords in INTENT_SECTION_KEYWORDS.values() for kw in keywords},
    key=len,
    reverse=True,  # 긴 키워드를 먼저 매칭해서 "사양"이 "제품 사양"보다 먼저 걸리는 일을 방지
)


def _matches_domain_keyword(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_TITLE_CHARS:
        return False
    if _SENTENCE_ENDING_PATTERN.search(stripped):
        return False  # "...설치했습니다." 같은 문장은 제외
    return any(stripped == kw or stripped.startswith(kw) or stripped.endswith(kw) for kw in _ALL_SECTION_KEYWORDS)


def is_heading_line(line: str) -> bool:
    """이 줄이 섹션 제목처럼 보이는지 판단한다 (절차 단계 문장과 구분해서)."""
    line = line.strip()
    if not line:
        return False
    if _matches_domain_keyword(line):
        return True
    if _ALL_CAPS_HEADING_PATTERN.fullmatch(line):
        return True
    match = _HEADING_PATTERN.match(line)
    if not match:
        return False
    title_part = match.group(1).strip()
    if len(title_part) > _MAX_HEADING_TITLE_CHARS:
        return False  # 너무 길면 목차성 제목이 아니라 본문 문장일 가능성이 높음
    if _SENTENCE_ENDING_PATTERN.search(title_part):
        return False  # "...한다." 처럼 문장으로 끝나면 절차 단계일 가능성이 높음, 제목 아님
    return True


class StructuredChunker(BaseChunker):
    """제목/섹션 구조를 우선 존중하는 청커. 구조가 없는 문서는 SemanticChunker로 위임한다."""

    def __init__(self, embedding_provider: BaseEmbeddingProvider, fallback_chunker: BaseChunker | None = None) -> None:
        self._embedding_provider = embedding_provider
        self._fallback = fallback_chunker or SemanticChunker(embedding_provider=embedding_provider)
        self._max_tokens = settings.chunk_max_tokens

    async def split(self, document_id: str, text: str) -> list[Chunk]:
        page_blocks = _PAGE_BLOCK_PATTERN.findall(text)
        if page_blocks:
            chunks: list[Chunk] = []
            for page_number_text, page_text in page_blocks:
                page_chunks = await self._split_page(document_id, page_text.strip())
                page_number = int(page_number_text)
                for chunk in page_chunks:
                    if chunk.page_number is None:
                        chunk.page_number = page_number
                chunks.extend(page_chunks)
            logger.info("페이지 경계를 보존해 청킹 완료: document_id=%s, pages=%d, chunks=%d", document_id, len(page_blocks), len(chunks))
            return chunks
        return await self._split_page(document_id, text)

    async def _split_page(self, document_id: str, text: str) -> list[Chunk]:
        table_texts, text_without_tables = self._extract_table_blocks(text)
        image_blocks = find_image_blocks(text_without_tables)
        text_without_special_blocks = strip_image_blocks(text_without_tables, _IMAGE_PLACEHOLDER)

        lines = text_without_special_blocks.split("\n")
        heading_line_indices = [i for i, line in enumerate(lines) if is_heading_line(line)]

        if len(heading_line_indices) < _MIN_HEADINGS_TO_TRIGGER:
            # 구조가 뚜렷하지 않은 문서 -> 표/이미지 처리까지 포함해서 이미 잘 하고 있는 SemanticChunker에 그대로 위임
            logger.info("제목이 %d개뿐이라 구조 기반 청킹 대신 의미기반 청킹으로 위임: document_id=%s", len(heading_line_indices), document_id)
            return await self._fallback.split(document_id, text)

        sections = self._split_into_sections(lines, heading_line_indices)
        sections = self._merge_small_sections(sections)

        chunks: list[Chunk] = []
        table_idx = 0
        image_idx = 0

        for heading_path, content in sections:
            # 섹션 하나 안에 표/이미지 placeholder가 섞여 있을 수 있으므로, 그 순서대로 다시 나눠서 처리
            combined_pattern = re.compile(f"({re.escape(_TABLE_PLACEHOLDER)}|{re.escape(_IMAGE_PLACEHOLDER)})")
            segments = combined_pattern.split(content)

            for segment in segments:
                if segment == _TABLE_PLACEHOLDER:
                    chunks.append(
                        Chunk(chunk_id=str(uuid.uuid4()), text=table_texts[table_idx], source_document_id=document_id, is_table=True)
                    )
                    table_idx += 1
                elif segment == _IMAGE_PLACEHOLDER:
                    image_path, caption = image_blocks[image_idx]
                    chunks.append(
                        Chunk(
                            chunk_id=str(uuid.uuid4()),
                            text=caption,
                            source_document_id=document_id,
                            is_table=False,
                            image_path=image_path,
                        )
                    )
                    image_idx += 1
                elif segment.strip():
                    chunks.extend(await self._split_section_text(document_id, heading_path, segment.strip()))

        logger.info(
            "구조 기반 청킹 완료 (document_id=%s): 섹션 %d개 -> 청크 %d개",
            document_id,
            len(sections),
            len(chunks),
        )
        return chunks

    def _extract_table_blocks(self, text: str) -> tuple[list[str], str]:
        table_texts = _TABLE_BLOCK_PATTERN.findall(text)
        replaced = _TABLE_BLOCK_PATTERN.sub(_TABLE_PLACEHOLDER, text)
        return table_texts, replaced

    def _split_into_sections(self, lines: list[str], heading_indices: list[int]) -> list[tuple[str, str]]:
        """
        줄 목록을 (제목 경로, 본문) 튜플 목록으로 나눈다.
        제목 경로는 마크다운 헤더 레벨/번호 깊이에 따라 "1. 설치 > 1.2 설치 절차"처럼 계층으로 표시한다.
        """
        sections: list[tuple[str, str]] = []
        heading_stack: list[str] = []  # 현재까지의 상위 제목들 (깊이 얕은 것부터)

        # 첫 제목 이전에 본문이 있으면(문서 서두 등) 제목 없는 섹션으로 취급
        if heading_indices[0] > 0:
            preamble = "\n".join(lines[: heading_indices[0]]).strip()
            if preamble:
                sections.append(("", preamble))

        for idx, heading_line_idx in enumerate(heading_indices):
            heading_text = lines[heading_line_idx].strip()
            depth = self._heading_depth(heading_text)

            # 스택에서 현재 깊이 이상인 제목들은 제거하고 새 제목을 쌓는다 (계층 구조 추적)
            heading_stack = heading_stack[: depth - 1] if depth >= 1 else []
            heading_stack.append(re.sub(r"^#{1,6}\s+", "", heading_text))  # 마크다운 # 기호는 경로 표시에서 제거

            content_start = heading_line_idx + 1
            content_end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(lines)
            content = "\n".join(lines[content_start:content_end]).strip()

            heading_path = " > ".join(heading_stack)
            sections.append((heading_path, content))

        return [(path, content) for path, content in sections if content]

    @staticmethod
    def _heading_depth(heading_text: str) -> int:
        """마크다운(#의 개수) 또는 번호 매기기(점의 개수+1)로 제목의 깊이를 추정한다."""
        md_match = re.match(r"^(#{1,6})\s", heading_text)
        if md_match:
            return len(md_match.group(1))
        num_match = re.match(r"^(\d+(?:\.\d+)*)\.?\s", heading_text)
        if num_match:
            return num_match.group(1).count(".") + 1
        return 1

    def _merge_small_sections(self, sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """
        토큰 수가 너무 적은 연속 섹션은 다음 섹션과 합친다 — 단, 같은 상위 섹션(제목 경로의 첫 번째
        구성요소가 같음) 아래일 때만 합친다. 완전히 다른 주제의 섹션끼리 합치면 청크의 섹션 라벨이
        엉뚱해질 수 있어서, 그런 경우엔 차라리 작은 채로 남긴다.
        """
        if not sections:
            return sections

        merged: list[tuple[str, str]] = []
        pending_path, pending_content = sections[0]

        def top_level(path: str) -> str:
            return path.split(" > ")[0] if path else ""

        for path, content in sections[1:]:
            same_top_level = top_level(path) == top_level(pending_path)
            if same_top_level and self._embedding_provider.count_tokens(pending_content) < _MIN_MERGE_TOKENS:
                # 합칠 때는 두 경로의 공통 조상만 남긴다 (더 구체적인 하위 제목 정보를 잃더라도,
                # 서로 다른 하위 섹션이 섞인 청크에 엉뚱한 하위 제목을 붙이는 것보다는 안전하다).
                pending_path = top_level(pending_path)
                pending_content = pending_content + "\n\n" + content
            else:
                merged.append((pending_path, pending_content))
                pending_path, pending_content = path, content

        merged.append((pending_path, pending_content))
        return merged

    async def _split_section_text(self, document_id: str, heading_path: str, content: str) -> list[Chunk]:
        """섹션 하나를 청크(들)로 만든다. 제목 경로를 본문 앞에 붙인다."""
        prefix = f"[섹션: {heading_path}]\n" if heading_path else ""

        if self._embedding_provider.count_tokens(content) <= self._max_tokens:
            return [
                Chunk(
                    chunk_id=str(uuid.uuid4()),
                    text=prefix + content,
                    source_document_id=document_id,
                    is_table=False,
                )
            ]

        # 섹션이 너무 크면, 그 안에서만 의미기반으로 추가 분할한다 (절차 단계가 안 잘리길 바라며
        # 문장 유사도 기준을 쓰되, 최소한 "같은 섹션 소속"이라는 정보는 유지한다).
        sub_chunks = await self._fallback._split_plain_text(document_id, content)  # noqa: SLF001 (같은 계층의 협력 클래스)
        for sub_chunk in sub_chunks:
            sub_chunk.text = prefix + sub_chunk.text
        return sub_chunks
