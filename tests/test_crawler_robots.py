from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.web_crawler.crawler import crawl

_HOME_HTML = """
<html><head><title>Home</title></head>
<body>
  <a href="/allowed">allowed</a>
  <a href="/blocked">blocked</a>
</body></html>
"""

_ALLOWED_HTML = "<html><head><title>Allowed</title></head><body>ok</body></html>"
_BLOCKED_HTML = "<html><head><title>Blocked</title></head><body>should not be crawled</body></html>"


class RobotsDisallowTests(unittest.TestCase):
    """robots.txt가 실제로 200으로 응답하며 특정 경로를 막는 경우"""

    def _fetch_fn(self, url: str) -> tuple[int, str]:
        self.requested_urls.append(url)
        if url == "https://example.com/robots.txt":
            return 200, "User-agent: *\nDisallow: /blocked\n"
        if url == "https://example.com/":
            return 200, _HOME_HTML
        if url == "https://example.com/allowed":
            return 200, _ALLOWED_HTML
        if url == "https://example.com/blocked":
            return 200, _BLOCKED_HTML
        return 404, ""

    def setUp(self) -> None:
        self.requested_urls: list[str] = []
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_disallowed_path_is_never_fetched(self) -> None:
        results = crawl(
            seed_url="https://example.com/",
            allowed_domain="example.com",
            output_dir=self.tmp_dir.name,
            max_pages=10,
            max_depth=2,
            fetch_fn=self._fetch_fn,
        )
        crawled_urls = {r.url for r in results}
        self.assertIn("https://example.com/", crawled_urls)
        self.assertIn("https://example.com/allowed", crawled_urls)
        self.assertNotIn("https://example.com/blocked", crawled_urls)
        # 크롤링 후보로 큐에는 들어갔더라도, 실제 페이지 요청은 절대 나가면 안 된다
        self.assertNotIn("https://example.com/blocked", self.requested_urls)

    def test_robots_txt_is_fetched_only_once_per_domain(self) -> None:
        crawl(
            seed_url="https://example.com/",
            allowed_domain="example.com",
            output_dir=self.tmp_dir.name,
            max_pages=10,
            max_depth=2,
            fetch_fn=self._fetch_fn,
        )
        robots_requests = [u for u in self.requested_urls if u.endswith("/robots.txt")]
        self.assertEqual(len(robots_requests), 1)


class RobotsFalsePositiveTests(unittest.TestCase):
    """robots.txt 요청 자체가 403/404로 실패하는 경우 -> 규칙 없음(전체 허용)으로 간주해야 함
    (표준 라이브러리 RobotFileParser.read()의 '403이면 전체 금지' 오탐을 피하는 게 핵심 목적)"""

    def _fetch_fn_403(self, url: str) -> tuple[int, str]:
        if url == "https://example.com/robots.txt":
            return 403, ""
        if url == "https://example.com/":
            return 200, "<html><head><title>Home</title></head><body>no links</body></html>"
        return 404, ""

    def _fetch_fn_404(self, url: str) -> tuple[int, str]:
        if url == "https://example.com/robots.txt":
            return 404, ""
        if url == "https://example.com/":
            return 200, "<html><head><title>Home</title></head><body>no links</body></html>"
        return 404, ""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_403_robots_does_not_block_crawling(self) -> None:
        results = crawl(
            seed_url="https://example.com/",
            allowed_domain="example.com",
            output_dir=self.tmp_dir.name,
            max_pages=5,
            max_depth=1,
            fetch_fn=self._fetch_fn_403,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/")

    def test_404_robots_does_not_block_crawling(self) -> None:
        results = crawl(
            seed_url="https://example.com/",
            allowed_domain="example.com",
            output_dir=self.tmp_dir.name,
            max_pages=5,
            max_depth=1,
            fetch_fn=self._fetch_fn_404,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/")


if __name__ == "__main__":
    unittest.main()
