"""
allganize_rag_ko_data/documents.csv 에 적힌 (domain, file_name, url)을 순회하며
실제 PDF 파일을 각 출처 웹페이지에서 찾아 다운로드하는 스크립트 (v2 — 성공률 개선판).

v1 대비 개선점:
  1. <a href="*.pdf"> 뿐 아니라, 한국 공공기관 게시판에서 흔한
     onclick="fn_egov_downFile(...)" 같은 JS 다운로드 패턴도 감지해서 별도로 표시한다
     (자동으로 못 뚫는 경우 "requires_js_handler"로 명확히 분류해서, 나중에 사이트별로
     골라서 손볼 수 있게 한다 — 무작정 실패로 뭉뚱그리지 않는다).
  2. 오래된 정부 사이트 특유의 SSL 인증서 체인 문제에 대응해, 검증 실패 시
     verify=False로 한 번 더 재시도한다.
  3. 파일명 매칭을 문자열 유사도(SequenceMatcher) + 토큰 겹침(Jaccard) 두 방식으로 계산해서
     더 높은 쪽을 채택한다 (예: "2024년 3월_2. 통화신용정책 운영.pdf"처럼 접두어가 다른 경우 보강).
  4. 실패 사유를 세분화해서 리포트에 남긴다 (페이지 접속 실패 / 링크 매칭 실패 /
     JS 다운로드 패턴 감지됨 / 다운로드했지만 PDF 아님 등).

사용법:
  cd allganize_rag_ko_data 폴더 안에서
  python download_pdfs.py
"""
from __future__ import annotations

import csv
import difflib
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "documents.csv"
OUTPUT_DIR = BASE_DIR / "documents"
REPORT_PATH = BASE_DIR / "download_report.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
REQUEST_TIMEOUT = 20
SIMILARITY_THRESHOLD = 0.4  # v1보다 완화 (토큰 유사도를 같이 쓰므로 임계값을 낮춰도 됨)

# 한국 공공기관 게시판(전자정부 표준프레임워크 등)에서 흔한 JS 다운로드 트리거 패턴
_JS_DOWNLOAD_PATTERN = re.compile(r"(fn_egov_downFile|fileDown|downloadFile|goDownload)", re.IGNORECASE)


def fetch_page(page_url: str) -> requests.Response:
    """페이지를 받아온다. SSL 인증서 오류 시 verify=False로 한 번 더 시도한다."""
    try:
        return requests.get(page_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.SSLError:
        return requests.get(page_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)


def _text_similarity(a: str, b: str) -> float:
    """문자열 유사도(SequenceMatcher)와 토큰 겹침(Jaccard) 중 더 높은 값을 반환한다."""
    seq_score = difflib.SequenceMatcher(None, a, b).ratio()

    tokens_a = set(re.findall(r"[가-힣A-Za-z0-9]+", a))
    tokens_b = set(re.findall(r"[가-힣A-Za-z0-9]+", b))
    if tokens_a and tokens_b:
        jaccard_score = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    else:
        jaccard_score = 0.0

    return max(seq_score, jaccard_score)


def find_best_pdf_link(page_url: str, target_filename: str) -> tuple[str | None, bool]:
    """
    페이지에서 target_filename과 가장 유사한 PDF 링크를 찾는다.
    반환값: (다운로드 URL 또는 None, JS 다운로드 패턴이 감지됐는지 여부)
    """
    response = fetch_page(page_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    best_href: str | None = None
    best_score = 0.0
    js_pattern_detected = False

    for a in soup.find_all("a"):
        onclick = a.get("onclick", "")
        if onclick and _JS_DOWNLOAD_PATTERN.search(onclick):
            js_pattern_detected = True  # href가 아니라 JS로 다운로드하는 사이트임을 표시만 해둔다

        href = a.get("href", "")
        if not href or (".pdf" not in href.lower() and "filedown" not in href.lower()):
            continue

        candidate_text = (a.get("title") or a.get_text() or "").strip()
        if not candidate_text:
            continue

        score = _text_similarity(candidate_text, target_filename)
        if score > best_score:
            best_score = score
            best_href = href

    if best_href and best_score >= SIMILARITY_THRESHOLD:
        return urljoin(page_url, best_href), js_pattern_detected
    return None, js_pattern_detected


def download_pdf(pdf_url: str, save_path: Path) -> bool:
    """pdf_url에서 실제로 PDF 바이트를 받아 save_path에 저장한다. 성공 여부를 반환한다."""
    try:
        response = requests.get(pdf_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.SSLError:
        response = requests.get(pdf_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        return False

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(response.content)
    return True


def main() -> None:
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"총 {len(rows)}개 문서 처리 시작")

    results: list[dict] = []
    for i, row in enumerate(rows, start=1):
        domain = row["domain"]
        file_name = row["file_name"]
        page_url = row["url"]
        save_path = OUTPUT_DIR / domain / file_name

        if save_path.exists():
            print(f"[{i}/{len(rows)}] 이미 존재함, 건너뜀: {file_name}")
            results.append({"file_name": file_name, "status": "skipped_exists"})
            continue

        try:
            pdf_url, js_detected = find_best_pdf_link(page_url, file_name)

            if not pdf_url:
                status = "requires_js_handler" if js_detected else "link_not_found"
                print(f"[{i}/{len(rows)}] {status}: {file_name}")
                results.append({"file_name": file_name, "status": status, "page_url": page_url})
                continue

            success = download_pdf(pdf_url, save_path)
            if success:
                print(f"[{i}/{len(rows)}] 다운로드 성공: {file_name}")
                results.append({"file_name": file_name, "status": "success", "pdf_url": pdf_url})
            else:
                print(f"[{i}/{len(rows)}] PDF 아님(내용 불일치): {file_name}")
                results.append({"file_name": file_name, "status": "not_pdf_content", "pdf_url": pdf_url})
        except requests.exceptions.RequestException as exc:
            print(f"[{i}/{len(rows)}] 페이지 접속 실패: {file_name} ({exc})")
            results.append({"file_name": file_name, "status": "page_fetch_error", "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] 실패: {file_name} ({exc})")
            results.append({"file_name": file_name, "status": "error", "error": str(exc)})

        time.sleep(0.5)  # 사이트에 과부하 주지 않도록 약간의 지연

    with open(REPORT_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file_name", "status", "page_url", "pdf_url", "error"])
        writer.writeheader()
        for r in results:
            writer.writerow(r)

    from collections import Counter

    status_counts = Counter(r["status"] for r in results)
    print("\n=== 결과 요약 ===")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}개")
    print(f"\n상세 결과는 {REPORT_PATH} 파일을 확인하세요.")
    print("특히 'requires_js_handler'로 표시된 항목들은 그 사이트의 다운로드 URL 패턴을 알려주시면 전용 처리 추가해드릴 수 있어요.")


if __name__ == "__main__":
    main()
