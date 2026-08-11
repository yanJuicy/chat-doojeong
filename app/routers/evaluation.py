"""API-only evaluation routes, intentionally absent from the browser console."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeAlias

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..api_models import ChatRequest, ChatResponse, ChatSource

PipelineEvent: TypeAlias = tuple[str, Any]
ChatPipeline: TypeAlias = Callable[[Request, ChatRequest], AsyncIterator[PipelineEvent]]


class EvalQuestion(BaseModel):
    question: str
    expected_document_id: str | None = None
    expected_filename: str | None = None
    expected_terms: list[str] = Field(default_factory=list)


class EvalRequest(BaseModel):
    questions: list[EvalQuestion]
    use_cache: bool = False


class EvalQuestionResult(BaseModel):
    question: str
    answer: str
    answer_preview: str
    top_similarity: float | None
    expected_document_id: str | None
    expected_filename: str | None
    expected_hit: bool | None
    expected_rank: int | None = None
    reciprocal_rank: float | None = None
    expected_terms_hit: bool | None = None
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)
    passed: bool | None = None
    error: str | None = None
    total_seconds: float
    stage_timings: list[dict] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)


class EvalResponse(BaseModel):
    results: list[EvalQuestionResult]
    total: int
    passed: int
    failed: int
    pass_rate: float | None
    avg_total_seconds: float
    avg_top_similarity: float | None
    hit_rate: float | None
    mean_reciprocal_rank: float | None
    answer_term_hit_rate: float | None


def _normalize_match_text(value: str) -> str:
    """Make fact-term matching resilient to Unicode and spacing differences."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", "", normalized)


def score_expectations(
    question: EvalQuestion,
    answer: str,
    sources: list[ChatSource],
) -> dict[str, Any]:
    """Score one answer using the public chat response contract."""
    source_expectation = bool(question.expected_document_id or question.expected_filename)
    expected_rank: int | None = None

    if source_expectation:
        expected_filename = (question.expected_filename or "").casefold()
        for rank, source in enumerate(sources, start=1):
            id_matches = (
                question.expected_document_id is None
                or source.document_id == question.expected_document_id
            )
            filename_matches = (
                question.expected_filename is None
                or expected_filename in source.filename.casefold()
            )
            if id_matches and filename_matches:
                expected_rank = rank
                break

    expected_hit = None if not source_expectation else expected_rank is not None
    reciprocal_rank = None if expected_rank is None else round(1.0 / expected_rank, 4)
    normalized_answer = _normalize_match_text(answer)
    matched_terms = [
        term for term in question.expected_terms if _normalize_match_text(term) in normalized_answer
    ]
    missing_terms = [
        term for term in question.expected_terms if _normalize_match_text(term) not in normalized_answer
    ]
    expected_terms_hit = None if not question.expected_terms else not missing_terms

    checks = [check for check in (expected_hit, expected_terms_hit) if check is not None]
    return {
        "expected_hit": expected_hit,
        "expected_rank": expected_rank,
        "reciprocal_rank": reciprocal_rank,
        "expected_terms_hit": expected_terms_hit,
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "passed": None if not checks else all(checks),
    }


def _evict_exact_question_cache(request: Request, question: str) -> None:
    cache = getattr(request.app.state, "question_cache", None)
    if hasattr(cache, "evict_exact"):
        cache.evict_exact(question)
        return
    if not isinstance(cache, list):
        return
    normalized = " ".join(question.casefold().split())
    cache[:] = [entry for entry in cache if entry.get("normalized_question") != normalized]


def create_evaluation_router(run_chat_pipeline: ChatPipeline) -> APIRouter:
    """Build the router with the chat pipeline injected to avoid import cycles."""
    router = APIRouter(tags=["evaluation"])

    async def evaluate_questions(request: Request, body: EvalRequest) -> EvalResponse:
        results: list[EvalQuestionResult] = []

        # The reranker and LLM share a GPU, so cases are intentionally sequential.
        for item in body.questions:
            if not body.use_cache:
                _evict_exact_question_cache(request, item.question)

            response: ChatResponse | None = None
            error: str | None = None
            stage_timings: list[dict] = []
            async for kind, payload in run_chat_pipeline(request, ChatRequest(question=item.question)):
                if kind == "timing":
                    stage_timings.append(payload)
                elif kind == "error":
                    error = f"[{payload['stage']}] {payload['message']}"
                    stage_timings = payload.get("stage_timings", stage_timings)
                    break
                elif kind == "result":
                    response = payload
                    stage_timings = response.stage_timings

            if response is None and error is None:
                error = "chat pipeline ended without a result"

            answer = response.answer if response is not None else ""
            sources = response.sources if response is not None else []
            score = score_expectations(item, answer, sources)
            if error is not None:
                score["passed"] = False

            results.append(
                EvalQuestionResult(
                    question=item.question,
                    answer=answer,
                    answer_preview=answer[:150] if answer else (error or ""),
                    top_similarity=sources[0].similarity if sources else None,
                    expected_document_id=item.expected_document_id,
                    expected_filename=item.expected_filename,
                    error=error,
                    total_seconds=round(
                        sum(float(timing.get("seconds", 0.0)) for timing in stage_timings), 3
                    ),
                    stage_timings=stage_timings,
                    sources=sources,
                    **score,
                )
            )

        scored = [result for result in results if result.passed is not None]
        source_scored = [result for result in results if result.expected_hit is not None]
        term_scored = [result for result in results if result.expected_terms_hit is not None]
        similarities = [result.top_similarity for result in results if result.top_similarity is not None]
        reciprocal_ranks = [result.reciprocal_rank or 0.0 for result in source_scored]
        passed = sum(result.passed is True for result in scored)

        return EvalResponse(
            results=results,
            total=len(results),
            passed=passed,
            failed=sum(result.passed is False for result in scored),
            pass_rate=round(passed / len(scored), 4) if scored else None,
            avg_total_seconds=(
                round(sum(result.total_seconds for result in results) / len(results), 3)
                if results
                else 0.0
            ),
            avg_top_similarity=(
                round(sum(similarities) / len(similarities), 4) if similarities else None
            ),
            hit_rate=(
                round(sum(result.expected_hit is True for result in source_scored) / len(source_scored), 4)
                if source_scored
                else None
            ),
            mean_reciprocal_rank=(
                round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
                if reciprocal_ranks
                else None
            ),
            answer_term_hit_rate=(
                round(
                    sum(result.expected_terms_hit is True for result in term_scored) / len(term_scored),
                    4,
                )
                if term_scored
                else None
            ),
        )

    router.add_api_route(
        "/api/evaluation/run",
        evaluate_questions,
        methods=["POST"],
        response_model=EvalResponse,
        name="run_evaluation",
    )
    router.add_api_route(
        "/api/debug/evaluate",
        evaluate_questions,
        methods=["POST"],
        response_model=EvalResponse,
        include_in_schema=False,
        name="run_evaluation_legacy",
    )
    return router
