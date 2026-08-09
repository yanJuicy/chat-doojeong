"""Run the API-only RAG evaluation suite and persist a reproducible result."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "docs" / "EVAL_QUESTIONS.json"
DEFAULT_OUTPUT = ROOT / "eval" / "latest_results.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ENDPOINT = "/api/evaluation/run"


def load_payload(path: Path, use_cache: bool) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    questions = raw.get("questions") if isinstance(raw, dict) else raw
    if not isinstance(questions, list) or not questions:
        raise ValueError("evaluation file must contain a non-empty question list")
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict) or not str(item.get("question", "")).strip():
            raise ValueError(f"question #{index} is missing a non-empty 'question'")
    return {"questions": questions, "use_cache": use_cache}


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"evaluation API returned HTTP {exc.code}: {detail}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the RAG regression evaluation harness")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="allow exact-question cache hits (disabled by default for honest regressions)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = load_payload(args.cases, args.use_cache)
        url = args.base_url.rstrip("/") + "/" + args.endpoint.lstrip("/")
        evaluation = post_json(url, payload, args.timeout)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    artifact = {
        "run": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cases": str(args.cases.resolve()),
            "url": url,
            "use_cache": args.use_cache,
        },
        "evaluation": evaluation,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    for result in evaluation.get("results", []):
        passed = result.get("passed")
        status = "PASS" if passed is True else "FAIL" if passed is False else "INFO"
        print(f"{status} {result.get('question', '')}", flush=True)
    summary_keys = (
        "total",
        "passed",
        "failed",
        "pass_rate",
        "hit_rate",
        "mean_reciprocal_rank",
        "answer_term_hit_rate",
    )
    print(json.dumps({key: evaluation.get(key) for key in summary_keys}, ensure_ascii=False))
    print(f"result: {args.output.resolve()}")
    return 2 if evaluation.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())

