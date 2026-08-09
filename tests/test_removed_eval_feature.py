from __future__ import annotations

import unittest
from pathlib import Path

from app.main import app


class RemovedEvaluationFeatureTests(unittest.TestCase):
    def test_evaluation_api_is_not_registered(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertNotIn("/api/debug/evaluate", paths)

    def test_console_does_not_render_comparison_tool(self) -> None:
        html = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("정확도·속도 비교 도구", html)
        self.assertNotIn("runEvaluation", html)


if __name__ == "__main__":
    unittest.main()
