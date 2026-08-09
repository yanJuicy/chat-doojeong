from __future__ import annotations

import unittest

from app.services.web_crawler.crawler import _same_domain


class SameDomainTests(unittest.TestCase):
    def test_exact_domain_matches(self) -> None:
        self.assertTrue(_same_domain("https://example.com/page", "example.com"))

    def test_subdomain_matches(self) -> None:
        self.assertTrue(_same_domain("https://docs.example.com/page", "example.com"))

    def test_lookalike_domain_does_not_match(self) -> None:
        # "evil-example.com".endswith("example.com")은 True지만, 실제로는 다른 도메인이다.
        self.assertFalse(_same_domain("https://evil-example.com/page", "example.com"))

    def test_port_is_ignored_for_comparison(self) -> None:
        self.assertTrue(_same_domain("https://example.com:8443/page", "example.com"))

    def test_case_insensitive(self) -> None:
        self.assertTrue(_same_domain("https://EXAMPLE.com/page", "example.com"))

    def test_unrelated_domain_does_not_match(self) -> None:
        self.assertFalse(_same_domain("https://another.org/page", "example.com"))


if __name__ == "__main__":
    unittest.main()
