"""OCR을 실행하지 않고 PDF 페이지의 digital/ocr/mixed 예상 분류를 감사한다."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pdf_page_classifier import classify_pdf_page, rectangle_coverage_ratios  # noqa: E402


def collect_pdf_paths(inputs: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for raw in inputs:
        candidate = Path(raw).resolve()
        if candidate.is_file() and candidate.suffix.casefold() == ".pdf":
            paths.add(candidate)
        elif candidate.is_dir():
            paths.update(path.resolve() for path in candidate.rglob("*.pdf"))
    return sorted(paths)


def collect_registered_pdf_paths(api_url: str, uploaded_dir: str) -> list[Path]:
    """문서 API의 ID와 `{document_id}_원본명.pdf` 저장 규칙으로 실제 등록 PDF만 찾는다."""
    with urllib.request.urlopen(api_url.rstrip("/") + "/api/documents", timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    documents = payload if isinstance(payload, list) else payload.get("documents", [])
    root = Path(uploaded_dir).resolve()
    paths: set[Path] = set()
    for document in documents:
        filename = str(document.get("filename", ""))
        document_id = str(document.get("document_id", ""))
        if not document_id or Path(filename).suffix.casefold() != ".pdf":
            continue
        matches = list(root.rglob(f"{document_id}_*.pdf"))
        if matches:
            paths.add(matches[0].resolve())
    return sorted(paths)


def collect_manifest_pdf_paths(manifest_path: str) -> list[Path]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return sorted(
        {
            Path(document["path"]).resolve()
            for document in payload.get("documents", [])
            if document.get("path") and Path(document["path"]).suffix.casefold() == ".pdf"
        }
    )


def image_rectangles(page) -> list[tuple[float, float, float, float]]:  # noqa: ANN001
    rectangles: list[tuple[float, float, float, float]] = []
    for image_info in page.get_images(full=True):
        try:
            rects = page.get_image_rects(image_info[0])
        except Exception:  # noqa: BLE001
            continue
        rectangles.extend((float(r.x0), float(r.y0), float(r.x1), float(r.y1)) for r in rects)
    return rectangles


def audit_pdf(path: Path, max_pages: int) -> dict:
    try:
        import fitz  # type: ignore
    except ImportError:
        return audit_pdf_with_pdfplumber(path, max_pages)

    pages: list[dict] = []
    with fitz.open(path) as document:
        page_limit = len(document) if max_pages <= 0 else min(len(document), max_pages)
        for page_index in range(page_limit):
            page = document[page_index]
            native_text = page.get_text().strip()
            page_rect = page.rect
            coverage, max_coverage = rectangle_coverage_ratios(
                (float(page_rect.x0), float(page_rect.y0), float(page_rect.x1), float(page_rect.y1)),
                image_rectangles(page),
            )
            profile = classify_pdf_page(
                native_text,
                image_coverage_ratio=coverage,
                max_image_coverage_ratio=max_coverage,
            )
            pages.append(
                {
                    "page": page_index + 1,
                    "mode": profile.mode,
                    "native_text_chars": profile.native_text_chars,
                    "native_quality_score": profile.native_quality.score,
                    "image_coverage_ratio": profile.image_coverage_ratio,
                    "max_image_coverage_ratio": profile.max_image_coverage_ratio,
                    "is_garbled": profile.is_garbled,
                    "reasons": profile.reasons,
                }
            )
        total_pages = len(document)

    counts = Counter(page["mode"] for page in pages)
    if counts and set(counts) == {"digital"}:
        document_type = "text_pdf"
    elif counts and set(counts) == {"ocr"}:
        document_type = "scan_pdf"
    else:
        document_type = "mixed_pdf"
    return {
        "path": str(path),
        "audit_backend": "pymupdf",
        "total_pages": total_pages,
        "audited_pages": len(pages),
        "document_type": document_type,
        "page_mode_counts": dict(counts),
        "pages": pages,
    }


def audit_pdf_with_pdfplumber(path: Path, max_pages: int) -> dict:
    """감사 환경에 PyMuPDF가 없을 때 pdfplumber로 같은 지표를 근사한다."""
    import pdfplumber  # type: ignore

    pages: list[dict] = []
    with pdfplumber.open(path) as document:
        page_limit = len(document.pages) if max_pages <= 0 else min(len(document.pages), max_pages)
        for page_index, page in enumerate(document.pages[:page_limit]):
            native_text = (page.extract_text() or "").strip()
            rectangles = [
                (
                    float(image.get("x0", 0)),
                    float(image.get("top", 0)),
                    float(image.get("x1", 0)),
                    float(image.get("bottom", 0)),
                )
                for image in page.images
            ]
            coverage, max_coverage = rectangle_coverage_ratios(
                (0.0, 0.0, float(page.width), float(page.height)), rectangles
            )
            profile = classify_pdf_page(
                native_text,
                image_coverage_ratio=coverage,
                max_image_coverage_ratio=max_coverage,
            )
            pages.append(
                {
                    "page": page_index + 1,
                    "mode": profile.mode,
                    "native_text_chars": profile.native_text_chars,
                    "native_quality_score": profile.native_quality.score,
                    "image_coverage_ratio": profile.image_coverage_ratio,
                    "max_image_coverage_ratio": profile.max_image_coverage_ratio,
                    "is_garbled": profile.is_garbled,
                    "reasons": profile.reasons,
                    "audit_backend": "pdfplumber",
                }
            )
        total_pages = len(document.pages)

    counts = Counter(page["mode"] for page in pages)
    if counts and set(counts) == {"digital"}:
        document_type = "text_pdf"
    elif counts and set(counts) == {"ocr"}:
        document_type = "scan_pdf"
    else:
        document_type = "mixed_pdf"
    return {
        "path": str(path),
        "audit_backend": "pdfplumber_approximation",
        "total_pages": total_pages,
        "audited_pages": len(pages),
        "document_type": document_type,
        "page_mode_counts": dict(counts),
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="PDF 파일 또는 PDF가 들어 있는 디렉터리")
    parser.add_argument("--registered-api", help="등록 문서만 감사할 앱 주소(예: http://127.0.0.1:8000)")
    parser.add_argument("--uploaded-dir", help="--registered-api와 함께 사용할 uploaded_files 경로")
    parser.add_argument("--manifest", help="이전 감사 JSON의 documents[].path 목록을 그대로 재검사")
    parser.add_argument("--max-pages", type=int, default=0, help="문서당 검사할 최대 페이지(0=전체)")
    parser.add_argument("--summary-only", action="store_true", help="페이지별 진단은 출력하지 않음")
    parser.add_argument("--output", help="JSON 결과 저장 경로")
    args = parser.parse_args()

    pdf_paths = collect_pdf_paths(args.paths)
    if args.registered_api:
        if not args.uploaded_dir:
            parser.error("--registered-api를 쓰려면 --uploaded-dir도 필요합니다.")
        pdf_paths = sorted(set(pdf_paths) | set(collect_registered_pdf_paths(args.registered_api, args.uploaded_dir)))
    if args.manifest:
        pdf_paths = sorted(set(pdf_paths) | set(collect_manifest_pdf_paths(args.manifest)))
    if not pdf_paths:
        parser.error("감사할 등록 PDF 또는 PDF 경로를 찾지 못했습니다.")
    results = [audit_pdf(path, args.max_pages) for path in pdf_paths]
    if args.summary_only:
        for result in results:
            result.pop("pages", None)
    report = {
        "pdf_count": len(results),
        "audit_backends": dict(Counter(item["audit_backend"] for item in results)),
        "document_type_counts": dict(Counter(item["document_type"] for item in results)),
        "documents": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
