"""
경계가 있는(bounded) 웹 크롤러.

주의: 이 모듈은 실제로 외부 인터넷에 접속한다. 완전 폐쇄망 서버 안에서 돌리면 안 되고,
인터넷이 되는 별도 환경에서 실행해서 그 결과(저장된 HTML + DB 레코드)를
폐쇄망으로 반입하는 용도로 쓴다 (지금 PDF를 수동으로 반입하시는 것과 같은 흐름).

동작 방식:
  - seed_url에서 시작해서 max_depth까지, 같은 도메인 링크만 따라간다 (allowed_domain 밖은 무시).
  - 각 페이지의 HTML을 파일로 저장하고, DB에 Document(status=UPLOADED, file_path=저장경로)를 만든다.
  - 실제 텍스트 추출(HtmlExtractor)은 여기서 하지 않는다 — extraction_worker가 나중에
    레지스트리를 통해 알아서 처리한다 (이 모듈은 "업로드"에 해당하는 역할만 한다).
  - 이미 방문한 URL은 건너뛰고(dedup), max_pages에 도달하면 중단한다.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; InternalRAGCrawler/1.0)"}
_REQUEST_TIMEOUT = 15


class CrawlResult:
    """크롤링된 페이지 하나의 결과 (DB 저장 전 상태)"""

    def __init__(self, url: str, html_path: str, title: str) -> None:
        self.url = url
        self.html_path = html_path
        self.title = title


def _same_domain(url: str, allowed_domain: str) -> bool:
    """netloc이 allowed_domain 자신이거나, 그 서브도메인일 때만 True.
    단순 endswith는 "evil-example.com"이 allowed_domain="example.com"에 걸리는 것을 못 막는다."""
    netloc = urlparse(url).netloc.partition(":")[0].lower()  # 포트 제거
    allowed = allowed_domain.lower()
    return netloc == allowed or netloc.endswith("." + allowed)


def _normalize_url(url: str) -> str:
    """쿼리스트링의 프래그먼트(#...)만 제거해서 중복 방문을 줄인다 (완벽한 정규화는 아님)."""
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def crawl(
    seed_url: str,
    allowed_domain: str,
    output_dir: str,
    max_pages: int = 50,
    max_depth: int = 2,
    fetch_fn=None,  # 테스트 시 실제 네트워크 없이 주입할 수 있도록 함 (기본은 requests.get)
) -> list[CrawlResult]:
    """
    seed_url에서 시작해 같은 도메인 안에서 링크를 따라가며 페이지를 수집한다.

    Args:
        fetch_fn: (url) -> (status_code, html_text) 를 반환하는 함수. 기본은 실제 HTTP 요청.
                  테스트 시 가짜 함수를 주입해서 네트워크 없이 크롤링 로직만 검증할 수 있다.

    Returns:
        수집된 페이지들의 CrawlResult 목록
    """
    if fetch_fn is None:
        fetch_fn = _default_fetch

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(_normalize_url(seed_url), 0)]
    results: list[CrawlResult] = []

    while queue and len(results) < max_pages:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not _same_domain(url, allowed_domain):
            logger.info("도메인 제한으로 건너뜀: %s", url)
            continue

        status_code, html = fetch_fn(url)
        if status_code != 200 or not html:
            logger.warning("페이지 가져오기 실패 (status=%s): %s", status_code, url)
            continue

        page_id = str(uuid.uuid4())
        html_path = output_path / f"{page_id}.html"
        html_path.write_text(html, encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url

        results.append(CrawlResult(url=url, html_path=str(html_path), title=title))
        logger.info("수집 완료 (depth=%d): %s", depth, url)

        if depth < max_depth:
            for a in soup.find_all("a", href=True):
                next_url = _normalize_url(urljoin(url, a["href"]))
                if next_url not in visited and _same_domain(next_url, allowed_domain):
                    queue.append((next_url, depth + 1))

    logger.info("크롤링 종료: 총 %d개 페이지 수집", len(results))
    return results


def _default_fetch(url: str) -> tuple[int, str]:
    try:
        response = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        return response.status_code, response.text
    except requests.exceptions.RequestException as exc:
        logger.warning("요청 실패: %s (%s)", url, exc)
        return 0, ""
