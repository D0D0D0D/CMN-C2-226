"""Tests for the CMN-C2-226 AGENTIC STAR Marketplace adapter."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.base import NullProvider, SecretProvider

import cli
from cli import MarketplaceGraph
from src.graph.graph import Graph

_CANARY = "CANARY"
_PAYLOAD = {
    "response_text": "The moon is cheese [9].",
    "retrieved_context": [],
    "system_prompt": "Use only retrieved context.",
    "constraints": [],
    "cross_run_samples": [],
    "mode": "realtime",
}


class _LeakyProvider(SecretProvider):
    """Runner provider that exposes values unless the adapter replaces it."""

    def get(self, key: str, default: str | None = None) -> str | None:
        del key, default
        return "leaked-value"


def _verified_context(*, hitl_allowed: bool = True) -> InvocationContext:
    return InvocationContext(
        session_id="marketplace-test",
        caller_id="marketplace-runner",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        hitl_allowed=hitl_allowed,
    )


def test_runner_input_context_is_discarded(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_invoke(self, user_input, session_id="", ctx=None, input_context=None):
        del self, session_id, ctx
        captured["user_input"] = user_input
        captured["input_context"] = input_context
        return {"status": AgentStatus.SUCCESS.value, "output": "ok"}

    monkeypatch.setattr(Graph, "invoke", fake_invoke)
    graph = MarketplaceGraph()
    raw_input = json.dumps(_PAYLOAD)
    graph.invoke(
        raw_input,
        ctx=_verified_context(),
        input_context={"conversation_history": [{"role": "user", "content": _CANARY}]},
    )

    assert captured["user_input"] == raw_input
    assert captured["input_context"] == {}


def test_invalid_input_gets_safe_nonempty_output() -> None:
    rejected_input = f"{_CANARY}: not JSON"
    graph = MarketplaceGraph()
    graph.compile()

    result = graph.invoke(rejected_input, ctx=_verified_context())

    assert result["status"] == AgentStatus.ERROR
    assert isinstance(result["output"], str) and result["output"]
    assert rejected_input not in result["output"]
    assert all(str(error) not in result["output"] for error in result["error_log"])


def test_oversized_input_gets_safe_nonempty_output() -> None:
    oversized_input = json.dumps({"response_text": "x" * 30_000})
    graph = MarketplaceGraph()
    graph.compile()

    result = graph.invoke(oversized_input, ctx=_verified_context())

    assert result["status"] == AgentStatus.ERROR
    assert result["output"] == cli._INVALID_INPUT_OUTPUT
    assert oversized_input not in result["output"]
    assert all(str(error) not in result["output"] for error in result["error_log"])


def test_runner_secret_provider_is_replaced_with_deny_all_provider() -> None:
    runner_provider = _LeakyProvider()
    graph = MarketplaceGraph()

    graph.provision_secrets(runner_provider)

    assert graph._secrets_provider is not runner_provider
    assert graph._secrets_provider.get("ANY_SECRET", "not-exposed") == "not-exposed"


def test_hitl_is_disabled_before_base_invoke(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_invoke(self, user_input, session_id="", ctx=None, input_context=None):
        del self, user_input, session_id, input_context
        captured["ctx"] = ctx
        return {"status": AgentStatus.SUCCESS.value, "output": "ok"}

    monkeypatch.setattr(Graph, "invoke", fake_invoke)
    MarketplaceGraph().invoke(json.dumps(_PAYLOAD), ctx=_verified_context(hitl_allowed=True))

    assert captured["ctx"].hitl_allowed is False


def test_success_output_matches_unadapted_graph() -> None:
    raw_input = json.dumps(_PAYLOAD)
    context = _verified_context()
    base = Graph()
    base.compile()
    marketplace = MarketplaceGraph()
    marketplace.compile()

    expected = base.invoke(raw_input, ctx=context)
    actual = marketplace.invoke(raw_input, ctx=context)

    assert actual["status"] == AgentStatus.SUCCESS
    assert actual["output"] == expected["output"]


def test_runner_lifecycle_processes_payload_without_history_leak() -> None:
    config = cli.load_agent_config(Path(cli.__file__).resolve().parent)
    graph = MarketplaceGraph(config=config)
    graph.compile()
    graph.provision_secrets(NullProvider())

    result = graph.invoke(
        json.dumps(_PAYLOAD),
        ctx=_verified_context(),
        input_context={"conversation_history": [{"role": "user", "content": _CANARY}]},
    )

    assert result["status"] == AgentStatus.SUCCESS
    assert result["output"]
    assert _CANARY not in json.dumps(result, ensure_ascii=False, default=str)
    assert result["qa_report"]["overall"] == "fail"
    assert result["qa_report"]["citation"]["score"] == 0.0
    assert result["qa_report"]["summary"]["total_findings"] == 1
    assert graph._secrets_provider.get("ANY_SECRET", "not-exposed") == "not-exposed"


def test_cli_module_imports_standalone() -> None:
    cli_path = Path(__file__).resolve().parents[2] / "cli.py"
    spec = importlib.util.spec_from_file_location("cli_import_test", cli_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    assert module.MarketplaceGraph.__name__ == "MarketplaceGraph"
