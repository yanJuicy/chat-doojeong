"""FastAPI 요청·응답 스키마.

엔드포인트 구현과 데이터 계약을 분리해 main.py가 실행 흐름에만 집중하도록 한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: str
    status: str
    is_duplicate: bool = False
    duplicate_of: str | None = None
    duplicate_similarity: float | None = None


class ZipUploadItem(BaseModel):
    document_id: str
    filename: str
    is_duplicate: bool = False
    duplicate_of: str | None = None


class ZipUploadResponse(BaseModel):
    created: list[ZipUploadItem]
    skipped: list[str]


class CrawlRequest(BaseModel):
    seed_url: str
    allowed_domain: str
    max_pages: int = 50
    max_depth: int = 2


class CrawlResponse(BaseModel):
    n_pages_crawled: int
    document_ids: list[str]


class RunWorkersResponse(BaseModel):
    extracted: int
    chunked: int
    embedded: int


class UpdateLabelsRequest(BaseModel):
    labels: list[str]


class ChatRequest(BaseModel):
    question: str


class ChatImage(BaseModel):
    image_url: str
    caption: str
    chunk_id: str


class ChatSource(BaseModel):
    document_id: str
    filename: str
    page_number: int | None = None
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    question_language: str
    n_context_chunks: int
    images: list[ChatImage] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)
    intent_scores: list[dict] = Field(default_factory=list)
    cache_hit: bool = False
    cache_similarity: float | None = None
    stage_timings: list[dict] = Field(default_factory=list)


class EvalQuestion(BaseModel):
    question: str
    expected_filename: str | None = None
    expected_terms: list[str] = Field(default_factory=list)


class EvalRequest(BaseModel):
    questions: list[EvalQuestion]


class EvalQuestionResult(BaseModel):
    question: str
    answer_preview: str
    top_similarity: float | None
    expected_filename: str | None
    expected_hit: bool | None
    expected_rank: int | None = None
    reciprocal_rank: float | None = None
    expected_terms_hit: bool | None = None
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)
    total_seconds: float
    stage_timings: list[dict]
    retrieval_trace: list[dict] = Field(default_factory=list)
    expected_stage_ranks: dict[str, int | None] = Field(default_factory=dict)
    drop_stage: str | None = None


class EvalResponse(BaseModel):
    results: list[EvalQuestionResult]
    avg_total_seconds: float
    avg_top_similarity: float | None
    hit_rate: float | None
    mean_reciprocal_rank: float | None = None
    answer_term_hit_rate: float | None = None
