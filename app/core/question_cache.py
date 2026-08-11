"""Conservative in-memory semantic cache for generated RAG answers.

Embedding similarity only finds candidates.  Reuse additionally requires the
question's exact identifiers, document-label hints, requested attributes,
primary intent, and comparison shape to be compatible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from .identifier_matching import extract_identifiers
from .label_matching import find_question_label_hints, is_comparison_question
from .similarity_utils import cosine_similarity


_ATTRIBUTE_TERMS: dict[str, tuple[str, ...]] = {
    "payload": ("가반하중", "적재하중", "하중", "payload"),
    "reach": ("작업반경", "도달거리", "도달 범위", "reach"),
    "dimensions": ("크기", "치수", "높이", "폭", "너비", "dimensions", "size"),
    "weight": ("무게", "중량", "weight"),
    "speed": ("속도", "speed"),
    "accuracy": ("정확도", "정밀도", "반복정밀도", "accuracy", "precision"),
    "power": ("전력", "소비전력", "전압", "전류", "power", "voltage", "current"),
    "pressure": ("압력", "pressure"),
    "temperature": ("온도", "temperature"),
    "certification": ("인증", "인증서", "규격", "certificate", "certification", "standard"),
    "warranty": ("보증", "warranty"),
    "price": ("가격", "비용", "price", "cost"),
    "installation": ("설치", "배선", "연결", "installation", "wiring"),
    "operation": ("사용법", "사용 방법", "조작", "운용", "operation", "programming"),
    "maintenance": ("유지보수", "정비", "점검", "maintenance"),
    "feature": ("기능", "특징", "장점", "feature"),
    "application": ("용도", "적용", "활용", "application", "use case"),
}


def normalize_question(question: str) -> str:
    return " ".join(question.casefold().split())


def extract_query_attributes(question: str) -> frozenset[str]:
    normalized = question.casefold()
    return frozenset(
        attribute
        for attribute, terms in _ATTRIBUTE_TERMS.items()
        if any(term in normalized for term in terms)
    )


def primary_intent(intent_scores: list[dict]) -> str | None:
    if not intent_scores:
        return None
    category = intent_scores[0].get("category")
    return str(category) if category else None


@dataclass(frozen=True)
class QuerySignature:
    identifiers: frozenset[str]
    labels: frozenset[str]
    attributes: frozenset[str]
    query_type: str
    intent: str | None

    def is_compatible_with(self, other: "QuerySignature") -> bool:
        return (
            self.identifiers == other.identifiers
            and self.labels == other.labels
            and self.attributes == other.attributes
            and self.query_type == other.query_type
            and self.intent == other.intent
        )


def build_query_signature(
    question: str,
    *,
    available_labels: list[str],
    intent_scores: list[dict],
) -> QuerySignature:
    return QuerySignature(
        identifiers=frozenset(extract_identifiers(question)),
        labels=frozenset(find_question_label_hints(question, available_labels)),
        attributes=extract_query_attributes(question),
        query_type="comparison" if is_comparison_question(question) else "single_lookup",
        intent=primary_intent(intent_scores),
    )


@dataclass
class QuestionCacheEntry:
    question: str
    normalized_question: str
    question_vector: list[float]
    answer: str
    signature: QuerySignature
    source_document_ids: frozenset[str]
    source_chunk_ids: frozenset[str]
    n_context_chunks: int
    images: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    intent_scores: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def identifiers(self) -> frozenset[str]:
        return self.signature.identifiers

    @property
    def labels(self) -> frozenset[str]:
        return self.signature.labels

    @property
    def attributes(self) -> frozenset[str]:
        return self.signature.attributes

    @property
    def query_type(self) -> str:
        return self.signature.query_type

    @property
    def intent(self) -> str | None:
        return self.signature.intent


@dataclass(frozen=True)
class CacheLookup:
    entry: QuestionCacheEntry
    similarity: float


class SemanticQuestionCache:
    """Small process-local cache with sliding expiry and LRU size eviction."""

    def __init__(
        self,
        *,
        max_size: int,
        ttl: timedelta,
        similarity_threshold: float,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.max_size = max(1, max_size)
        self.ttl = ttl
        self.similarity_threshold = similarity_threshold
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._entries: list[QuestionCacheEntry] = []

    @property
    def entries(self) -> tuple[QuestionCacheEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def cleanup_expired(self) -> int:
        now = self._now_provider()
        before = len(self._entries)
        self._entries = [entry for entry in self._entries if entry.expires_at > now]
        return before - len(self._entries)

    def get_exact(self, question: str) -> CacheLookup | None:
        self.cleanup_expired()
        normalized = normalize_question(question)
        for entry in self._entries:
            if entry.normalized_question == normalized:
                self._touch(entry)
                return CacheLookup(entry=entry, similarity=1.0)
        return None

    def get_semantic(
        self,
        question_vector: list[float],
        signature: QuerySignature,
    ) -> CacheLookup | None:
        self.cleanup_expired()
        best: CacheLookup | None = None
        for entry in self._entries:
            similarity = cosine_similarity(question_vector, entry.question_vector)
            if similarity < self.similarity_threshold:
                continue
            if not signature.is_compatible_with(entry.signature):
                continue
            if best is None or similarity > best.similarity:
                best = CacheLookup(entry=entry, similarity=similarity)
        if best is not None:
            self._touch(best.entry)
        return best

    def store(
        self,
        *,
        question: str,
        question_vector: list[float],
        answer: str,
        signature: QuerySignature,
        source_document_ids: set[str],
        source_chunk_ids: set[str],
        n_context_chunks: int,
        images: list,
        sources: list,
        intent_scores: list[dict],
    ) -> QuestionCacheEntry:
        self.cleanup_expired()
        normalized = normalize_question(question)
        self._entries = [entry for entry in self._entries if entry.normalized_question != normalized]
        now = self._now_provider()
        entry = QuestionCacheEntry(
            question=question,
            normalized_question=normalized,
            question_vector=list(question_vector),
            answer=answer,
            signature=signature,
            source_document_ids=frozenset(source_document_ids),
            source_chunk_ids=frozenset(source_chunk_ids),
            n_context_chunks=n_context_chunks,
            images=list(images),
            sources=list(sources),
            intent_scores=list(intent_scores),
            created_at=now,
            last_used_at=now,
            expires_at=now + self.ttl,
        )
        self._entries.append(entry)
        if len(self._entries) > self.max_size:
            self._entries.sort(key=lambda cached: cached.last_used_at)
            del self._entries[: len(self._entries) - self.max_size]
        return entry

    def invalidate_document(self, document_id: str) -> int:
        before = len(self._entries)
        self._entries = [
            entry for entry in self._entries if document_id not in entry.source_document_ids
        ]
        return before - len(self._entries)

    def evict_exact(self, question: str) -> int:
        normalized = normalize_question(question)
        before = len(self._entries)
        self._entries = [
            entry for entry in self._entries if entry.normalized_question != normalized
        ]
        return before - len(self._entries)

    def _touch(self, entry: QuestionCacheEntry) -> None:
        now = self._now_provider()
        entry.last_used_at = now
        entry.expires_at = now + self.ttl
