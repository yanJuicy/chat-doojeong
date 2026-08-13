# API-only evaluation

The browser console intentionally has no evaluation panel. Evaluation remains available through
the separate `app.routers.evaluation` router.

- `POST /api/evaluation/run`: canonical evaluation endpoint

Run the default evaluation set against a running server:

```powershell
python scripts/run_regression_eval.py
```

Choose another case file or output path:

```powershell
python scripts/run_regression_eval.py `
  --cases docs/EVAL_ADVERSARIAL_QUESTIONS.json `
  --output eval/adversarial_results.json
```

The case file may be either a JSON array or an object with a `questions` array. Each case supports
`question`, `expected_document_id`, `expected_filename`, and `expected_terms`.

Exact-question cache reuse is disabled by default so configuration regressions are measured.
Pass `--use-cache` only when cache behavior itself is under evaluation. The harness returns exit
code `0` when all scored cases pass, `2` when an expectation fails, and `1` for input, network, or
API errors.

