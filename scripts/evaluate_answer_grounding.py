"""Repeat false-premise answer checks against the local debug evaluation API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


CASES = [
    {
        "question": "두정테크는 CO2 가스메탈아크용접을 쓰나?",
        "expected_terms": ["탄산가스 아크용접"],
        "correction_required": True,
        "forbidden_phrases": ["가스메탈아크용접을 사용합니다", "같은 용접 방식"],
    },
    {
        "question": "두정테크 용접 방식은 GMAW라고 보면 돼?",
        "expected_terms": ["탄산가스 아크용접"],
        "correction_required": True,
        "forbidden_phrases": ["gmaw라고 볼 수", "gmaw와는 다른", "다른 용접 방식"],
    },
    {
        "question": "두정테크는 MIG 용접을 사용하는 회사가 맞지?",
        "expected_terms": ["탄산가스 아크용접"],
        "correction_required": True,
        "forbidden_phrases": ["mig 용접을 사용합니다"],
    },
    {
        "question": "두정테크는 아르곤 가스를 이용한 용접을 하지?",
        "expected_terms": ["탄산가스 아크용접"],
        "correction_required": True,
        "forbidden_phrases": [],
    },
    {
        "question": "두정테크는 레이저빔용접을 사용하지?",
        "expected_terms": ["탄산가스 아크용접"],
        "correction_required": True,
        "forbidden_phrases": ["레이저빔용접을 사용하지", "사용하지 않는다고 볼 수"],
    },
    {
        "question": "두정테크 용접 방식은 탄산가스 아크용접이 맞아?",
        "expected_terms": ["탄산가스 아크용접"],
        "correction_required": False,
        "forbidden_phrases": [],
    },
    {
        "question": "RB5-850의 가반하중은 16kg이 맞지?",
        "expected_terms": ["5kg"],
        "correction_required": False,
        "forbidden_phrases": ["가반하중은 16kg입니다"],
    },
]

CORRECTION_MARKERS = (
    "자료에는",
    "자료에서는",
    "자료에 따르면",
    "표기",
    "확인되지",
    "확인할 수 없",
    "명시되지",
    "아닙니다",
    "정확하지 않",
    "하지 않습니다",
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/debug/evaluate")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    questions = []
    for _ in range(args.rounds):
        questions.extend(
            {"question": case["question"], "expected_terms": case["expected_terms"]}
            for case in CASES
        )

    payload = json.dumps({"questions": questions}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=1800) as response:  # noqa: S310 - fixed local URL by default
        data = json.loads(response.read().decode("utf-8"))

    checks = []
    for index, result in enumerate(data["results"]):
        case = CASES[index % len(CASES)]
        answer = result["answer_preview"].strip()
        term_hit = all(term.casefold() in answer.casefold() for term in case["expected_terms"])
        correction_hit = any(marker in answer for marker in CORRECTION_MARKERS)
        starts_with_yes = answer.startswith(("네", "예"))
        forbidden_hits = [
            phrase
            for phrase in case.get("forbidden_phrases", [])
            if phrase.casefold() in answer.casefold()
        ]
        passed = term_hit and (
            not case["correction_required"] or (correction_hit and not starts_with_yes)
        ) and not forbidden_hits
        checks.append(
            {
                "round": index // len(CASES) + 1,
                "question": case["question"],
                "passed": passed,
                "term_hit": term_hit,
                "correction_hit": correction_hit,
                "starts_with_yes": starts_with_yes,
                "forbidden_hits": forbidden_hits,
                "answer": answer,
            }
        )

    output = {
        "passed": sum(check["passed"] for check in checks),
        "total": len(checks),
        "failures": [check for check in checks if not check["passed"]],
        "checks": checks,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["passed"] == output["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
