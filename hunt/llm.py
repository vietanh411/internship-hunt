"""Optional Claude integration (resume rewording, cover letters, contextual
answers). Every output is passed through the fact guard by its caller; when no
credentials are configured the deterministic code paths are used instead.

Credentials resolve the standard SDK way: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN,
or an `ant auth login` profile."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic

from hunt.config import get_settings

log = logging.getLogger(__name__)


def _has_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()


class LLM:
    def __init__(self) -> None:
        s = get_settings()
        self.model = s.llm_model
        self.enabled = s.llm_enabled and _has_credentials()
        self._client: anthropic.Anthropic | None = None
        self.calls = 0
        self.failures = 0

    @property
    def available(self) -> bool:
        return self.enabled

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(max_retries=3, timeout=180.0)
        return self._client

    def json(self, system: str, user: str, schema: dict, effort: str = "medium",
             max_tokens: int = 8000) -> dict | None:
        """One structured-output call. Returns parsed JSON or None on any failure
        (callers fall back to deterministic behaviour)."""
        if not self.enabled:
            return None
        self.calls += 1
        try:
            resp = self._get_client().beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AuthenticationError:
            log.error("Anthropic credentials rejected; disabling LLM features for this process")
            self.enabled = False
            self.failures += 1
            return None
        except anthropic.BadRequestError as e:
            log.error("LLM request rejected: %s", e.message)
            self.failures += 1
            return None
        except anthropic.RateLimitError:
            log.warning("LLM rate limited after SDK retries")
            self.failures += 1
            return None
        except anthropic.APIStatusError as e:
            log.warning("LLM API error %s", e.status_code)
            self.failures += 1
            return None
        except anthropic.APIConnectionError:
            log.warning("LLM connection error")
            self.failures += 1
            return None
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("LLM stopped with %s", resp.stop_reason)
            self.failures += 1
            return None
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text:
            self.failures += 1
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.failures += 1
            return None


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm


def reset_llm() -> None:
    global _llm
    _llm = None
