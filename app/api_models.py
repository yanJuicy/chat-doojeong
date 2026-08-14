"""FastAPI 요청·응답 스키마.

엔드포인트 구현과 데이터 계약을 분리해 main.py가 실행 흐름에만 집중하도록 한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    document_id: str
    status: str
    is_duplicate: bool = False


class ZipUploadItem(BaseModel):
    document_id: str
    filename: str
    is_duplicate: bool = False


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


class RunWorkersAcceptedResponse(BaseModel):
    status: str


class UpdateLabelsRequest(BaseModel):
    labels: list[str]


class DeleteDocumentsRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=100)


class DeleteDocumentIssue(BaseModel):
    document_id: str
    reason: str


class DeleteDocumentsResponse(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    blocked: list[DeleteDocumentIssue] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    cleanup_warnings: list[str] = Field(default_factory=list)


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
