from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from pydantic_ai.models.openai import OpenAIChatModel

from agent_core import (
    configured_provider_names,
    provider_health,
    run_ahmed,
)


class ModelProviderTests(unittest.TestCase):
    def test_configured_provider_names_include_gemini_and_openai(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-gemini-key",
                "AI_INTEGRATIONS_OPENAI_API_KEY": "test-openai-key",
                "AI_INTEGRATIONS_OPENAI_BASE_URL": "https://openai.example.test/v1",
            },
        ):
            self.assertEqual(configured_provider_names(), ["gemini", "openai"])

    def test_openai_health_requires_both_integration_variables(self) -> None:
        with patch.dict(
            os.environ,
            {"AI_INTEGRATIONS_OPENAI_API_KEY": "test-openai-key"},
            clear=False,
        ):
            with patch.dict(os.environ, {"AI_INTEGRATIONS_OPENAI_BASE_URL": ""}):
                self.assertEqual(provider_health("openai")["status"], "NOT_CONFIGURED")

    def test_openai_candidate_uses_chat_model_without_network_call(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AI_INTEGRATIONS_OPENAI_API_KEY": "test-openai-key",
                "AI_INTEGRATIONS_OPENAI_BASE_URL": "https://openai.example.test/v1",
            },
        ):
            from agent_core import _configured_providers

            openai_candidate = next(
                candidate
                for candidate in _configured_providers()
                if candidate.name == "openai"
            )
            self.assertIsInstance(openai_candidate.model, OpenAIChatModel)

    def test_invalid_provider_is_rejected_before_model_call(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(run_ahmed("test", provider="invalid"))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()