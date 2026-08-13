"""
의미기반(Semantic) 청킹 구현체.

동작 방식:
  1. 표 블록(<!-- TABLE_BLOCK_START --> ~ <!-- TABLE_BLOCK_END -->)과
     이미지 블록(<!-- IMAGE_BLOCK_START ... --> ~ <!-- IMAGE_BLOCK_END -->)을 먼저 분리해서
     각각 통째로 하나의 청크(is_table=True 또는 image_path 지정)로 만든다.
  2. 나머지 본문은 문장 단위로 분리(kiwipiepy)한 뒤, 인접 문장 간 임베딩 유사도를 계산해서
     유사도가 임계값 밑으로 떨어지거나 최대 토큰 수를 넘기면 새 청크로 분할한다.
"""
from __future__ import annotations

import logging
import re
import uuid

import numpy as np

from ..config import settings
from .chunking import BaseChunker, Chunk
from .embeddings import BaseEmbeddingProvider
from .image_markdown import find_image_blocks, strip_image_blocks

logger = logging.getLogger(__name__)

_TABLE_BLOCK_PATTERN = re.compile(
    r"<!-- TABLE_BLOCK_START -->(.*?)<!-- TABLE_BLOCK_END -->",
    re.DOTALL,
)
_TABLE_PLACEHOLDER = "\uE000TABLE_PLACEHOLDER\uE000"  # 사용자 영역 문자로 충돌 방지
_IMAGE_PLACEHOLDER = "\uE001IMAGE_PLACEHOLDER\uE001"


class SemanticChunker(BaseChunker):
    """임베딩 유사도 기반으로 문장을 그룹핑해 청크를 만드는 청커"""

    def __init__(self, embedding_provider: BaseEmbeddingProvider) -> None:
        self._embedding_provider = embedding_provider
        self._similarity_threshold = settings.chunk_similarity_threshold
        self._min_tokens = settings.chunk_min_tokens
        self._max_tokens = settings.chunk_max_tokens  # 실제 토크나이저로 세므로 글자수 근사가 더 이상 필요 없음

        try:
            from kiwipiepy import Kiwi  # type: ignore

            self._kiwi = Kiwi()
        except ImportError:
            logger.warning("kiwipiepy 미설치 — 정규식 기반 문장 분리로 폴백합니다.")
            self._kiwi = None

    async def split(self, document_id: str, text: str) -> list[Chunk]:
        """문서 텍스트를 의미 단위 청크로 분할한다."""
        # 표와 이미지 블록을 먼저 걷어내서 별도 청크로 만들고, 본문에는 자리표시자만 남긴다.
        # 두 종류가 뒤섞여 순서대로 등장할 수 있으므로, 각 자리표시자가 나온 순서를 함께 기록해둔다.
        table_texts, text_without_tables = self._extract_table_blocks(text)
        image_blocks = find_image_blocks(text_without_tables)
        text_without_special_blocks = strip_image_blocks(text_without_tables, _IMAGE_PLACEHOLDER)

        # 표/이미지 자리표시자가 뒤섞인 순서 그대로 특수 청크 목록을 만든다.
        combined_placeholder_pattern = re.compile(f"({re.escape(_TABLE_PLACEHOLDER)}|{re.escape(_IMAGE_PLACEHOLDER)})")
        segments = combined_placeholder_pattern.split(text_without_special_blocks)

        chunks: list[Chunk] = []
        table_idx = 0
        image_idx = 0

        for segment in segments:
            if segment == _TABLE_PLACEHOLDER:
                chunks.append(
                    Chunk(
                        chunk_id=str(uuid.uuid4()),
                        text=table_texts[table_idx],
                        source_document_id=document_id,
                        is_table=True,
                    )
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
                chunks.extend(await self._split_plain_text(document_id, segment))

        logger.info(
            "청킹 완료 (document_id=%s): 총 %d개 청크 (표 %d개, 이미지 %d개)",
            document_id,
            len(chunks),
            len(table_texts),
            len(image_blocks),
        )
        return chunks

    def _extract_table_blocks(self, text: str) -> tuple[list[str], str]:
        """표 블록 마커 사이 내용을 뽑아내고, 본문에는 자리 표시자를 남긴다."""
        table_texts = _TABLE_BLOCK_PATTERN.findall(text)
        replaced = _TABLE_BLOCK_PATTERN.sub(_TABLE_PLACEHOLDER, text)
        return table_texts, replaced

    def _split_sentences(self, text: str) -> list[str]:
        """텍스트를 문장 단위로 분리한다."""
        if self._kiwi is not None:
            return [sent.text.strip() for sent in self._kiwi.split_into_sents(text) if sent.text.strip()]

        # kiwipiepy 미설치 시 폴백: 문장부호 기준 정규식 분리
        raw_sentences = re.split(r"(?<=[.!?。])\s+", text)
        return [s.strip() for s in raw_sentences if s.strip()]

    async def _split_plain_text(self, document_id: str, text: str) -> list[Chunk]:
        """
        표가 아닌 일반 텍스트를 의미기반으로 청킹한다.

        속도 최적화: 청크가 문장 딱 하나로만 이루어지는 경우(짧은 문단, 목록 항목 등에서 흔함),
        경계 판단을 위해 이미 계산해둔 그 문장의 임베딩이 곧 그 청크 전체의 임베딩과 동일하므로,
        나중에 embedding_worker가 저장용으로 또 임베딩하지 않도록 여기서 넘겨준다.
        (문장이 여러 개 합쳐진 청크는 "합쳐진 전체"의 임베딩이 필요해서 이 방식을 못 쓴다 —
        여러 문장 임베딩의 평균은 전체를 한 번에 임베딩한 것과 다르기 때문이다.)

        Parent-Child: 이 세그먼트가 청크 여러 개로 쪼개지면, 각 자식 청크에 이 세그먼트
        전체 텍스트를 parent_text로 붙여서 답변 생성 시 맥락 손실을 줄인다. 애초에 청크가
        하나로 안 쪼개지면(세그먼트 자체가 이미 작음) parent_text는 비워둔다 — 자기 자신을
        parent로 중복 저장할 필요가 없다.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        embeddings = await self._embedding_provider.embed_documents(sentences)
        embeddings_np = np.array(embeddings)

        chunks: list[Chunk] = []
        current_indices: list[int] = [0]
        current_token_count = self._embedding_provider.count_tokens(sentences[0])

        for i in range(1, len(sentences)):
            similarity = self._cosine_similarity(embeddings_np[i - 1], embeddings_np[i])
            sentence_token_count = self._embedding_provider.count_tokens(sentences[i])

            exceeds_max_tokens = current_token_count + sentence_token_count > self._max_tokens
            # 문장 유사도는 같은 주제 안에서도 흔들린다. 최소 길이를 채우기 전에는 의미 점수만으로
            # 자르지 않아 50~100자짜리 파편 청크가 대량 생성되는 것을 막는다.
            drops_below_threshold = (
                current_token_count >= self._min_tokens
                and similarity < self._similarity_threshold
            )

            if exceeds_max_tokens or drops_below_threshold:
                chunks.append(self._make_chunk(document_id, sentences, embeddings_np, current_indices))
                current_indices = [i]
                current_token_count = sentence_token_count
            else:
                current_indices.append(i)
                current_token_count += sentence_token_count

        if current_indices:
            chunks.append(self._make_chunk(document_id, sentences, embeddings_np, current_indices))

        if len(chunks) > 1:
            for chunk in chunks:
                chunk.parent_text = text

        return chunks

    @staticmethod
    def _make_chunk(document_id: str, sentences: list[str], embeddings_np: np.ndarray, indices: list[int]) -> Chunk:
        chunk_sentences = [sentences[i] for i in indices]
        # 문장이 딱 하나면, 그 문장의 임베딩 = 이 청크 전체의 임베딩이므로 재사용한다.
        precomputed = embeddings_np[indices[0]].tolist() if len(indices) == 1 else None
        return Chunk(
            chunk_id=str(uuid.uuid4()),
            text=" ".join(chunk_sentences),
            source_document_id=document_id,
            is_table=False,
            precomputed_dense_vector=precomputed,
        )

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)
