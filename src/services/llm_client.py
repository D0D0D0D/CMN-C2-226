"""AgentCore Platform v1.0 — CMN-C2-226 LLM-assist injection seam.

Instruction-drift (②) is rule-based by default in v1 (deterministic, no LLM cost,
no secrets). This module is the *injection seam* for an optional LLM-assist pass
that a deployment may wire in later for low-confidence drift cases.

v1 ships a NullLLMClient (disabled): nodes call `assist_enabled()` and skip the
LLM path. To enable, inject a real client that fulfils `LLMClient.judge()` and
flip `llm_assist.enabled: true` in config/config.yaml. Secrets MUST be accessed via
`ctx.secrets.require(...)` inside the real client — never `os.environ`.
"""

from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    """Minimal protocol for an optional drift-assist judge."""

    def judge(self, prompt: str, response: str, rule: str) -> dict:
        """Return {"violated": bool, "confidence": float, "reason": str}."""
        ...


class NullLLMClient:
    """Default no-op client — v1 runs rule-based only (LLM assist disabled)."""

    enabled: bool = False

    def judge(self, prompt: str, response: str, rule: str) -> dict:
        return {"violated": False, "confidence": 0.0, "reason": "llm-assist disabled (v1 rule-based only)"}


def default_client() -> NullLLMClient:
    """Return the v1 default (disabled) client. Override via dependency injection."""
    return NullLLMClient()
