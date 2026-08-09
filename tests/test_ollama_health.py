from __future__ import annotations

import unittest

from app.core.qwen_ollama_provider import ollama_model_is_available


class OllamaHealthTests(unittest.TestCase):
    def test_finds_configured_model_by_name_or_model_field(self) -> None:
        payload = {
            "models": [
                {"name": "qwen3:8b", "model": "qwen3:8b"},
                {"name": "qwen3-vl:2b-instruct"},
            ]
        }

        self.assertTrue(ollama_model_is_available(payload, "qwen3:8b"))
        self.assertTrue(ollama_model_is_available(payload, "QWEN3-VL:2B-INSTRUCT"))

    def test_adds_latest_tag_when_both_sides_omit_or_include_it(self) -> None:
        payload = {"models": [{"name": "custom-model:latest"}]}

        self.assertTrue(ollama_model_is_available(payload, "custom-model"))

    def test_does_not_accept_running_server_without_requested_model(self) -> None:
        payload = {"models": [{"name": "qwen3:4b"}]}

        self.assertFalse(ollama_model_is_available(payload, "qwen3:8b"))


if __name__ == "__main__":
    unittest.main()
