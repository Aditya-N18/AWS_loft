from __future__ import annotations

import json
import re
from typing import Any

from agent.config import settings

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


class AnthropicClient:
    def __init__(self) -> None:
        self.mock_mode = settings.agent_mock_mode or not settings.has_anthropic
        self.model = settings.anthropic_model
        self._client = None
        if not self.mock_mode and anthropic is not None:
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if self.mock_mode:
            raise RuntimeError("Anthropic mock mode active — caller should provide fallback")

        assert self._client is not None
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
        return _extract_json(text)
