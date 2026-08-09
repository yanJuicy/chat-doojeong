from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app.api_models import ChatResponse, ChatSource
from app.main import app
from app.routers.evaluation import (
    EvalQuestion,
    EvalRequest,
    create_evaluation_router,
    score_expectations,
)


class RemovedEvaluationFeatureTests(unittest.TestCase):
    def test_evaluation_api_is_registered_outside_console(self) -> None:
        self.assertEqual("/api/evaluation/run", str(app.url_path_for("run_evaluation")))
        self.assertEqual(
            "/api/debug/evaluate",
            str(app.url_path_for("run_evaluation_legacy")),
        )

    def test_console_does_not_render_comparison_tool(self) -> None:
        html = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("정확도·속도 비교 도구", html)
        self.assertNotIn("runEvaluation", html)

    def test_expectations_are_scored_from_chat_response(self) -> None:
        result = score_expectations(
            EvalQuestion(
                question="serial number?",
                expected_document_id="doc-2",
                expected_terms=["ABC-123"],
            ),
            "The serial number is ABC-123.",
            [
                ChatSource(document_id="doc-1", filename="one.pdf", similarity=0.91),
                ChatSource(document_id="doc-2", filename="two.pdf", similarity=0.82),
            ],
        )

        self.assertTrue(result["passed"])
        self.assertEqual(2, result["expected_rank"])
        self.assertEqual(0.5, result["reciprocal_rank"])

    def test_term_scoring_ignores_spacing_differences(self) -> None:
        result = score_expectations(
            EvalQuestion(question="what is it?", expected_terms=["촉매변환기"]),
            "문서에는 촉매 변환기로 표기되어 있습니다.",
            [],
        )

        self.assertTrue(result["expected_terms_hit"])
        self.assertTrue(result["passed"])


class EvaluationRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_runs_injected_pipeline_and_summarizes_result(self) -> None:
        async def fake_pipeline(_request, body):
            yield ("timing", {"stage": "search", "seconds": 0.25})
            yield (
                "result",
                ChatResponse(
                    answer=f"{body.question}: expected value",
                    question_language="en",
                    n_context_chunks=1,
                    sources=[
                        ChatSource(
                            document_id="doc-1",
                            filename="manual.pdf",
                            similarity=0.88,
                        )
                    ],
                    stage_timings=[{"stage": "search", "seconds": 0.25}],
                ),
            )

        router = create_evaluation_router(fake_pipeline)
        route = next(route for route in router.routes if route.name == "run_evaluation")
        request = Request(
            {
                "type": "http",
                "app": SimpleNamespace(state=SimpleNamespace(question_cache=[])),
            }
        )
        response = await route.endpoint(
            request,
            EvalRequest(
                questions=[
                    EvalQuestion(
                        question="question",
                        expected_filename="manual.pdf",
                        expected_terms=["expected value"],
                    )
                ]
            ),
        )

        self.assertEqual(1, response.total)
        self.assertEqual(1, response.passed)
        self.assertEqual(0, response.failed)
        self.assertEqual(1.0, response.mean_reciprocal_rank)


if __name__ == "__main__":
    unittest.main()
