"""AGENTIC STAR Marketplace entry adapter for CMN-C2-226."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.secrets.base import SecretProvider

try:
    from framework.utils.config_loader import load_agent_config
except ImportError:  # AgentCore 1.0.0 / 1.0.1 compatibility
    from framework.utils.config_loader import load_config

    def load_agent_config(agent_dir: Path) -> dict[str, Any]:
        config_path = agent_dir / "config" / "config.yaml"
        return load_config(str(config_path)) if config_path.exists() else {}


try:
    from shared.bootstrap import run_agent_marketplace
except ModuleNotFoundError as exc:  # AgentCore 1.0.0 / 1.0.1 compatibility
    if exc.name != "shared.bootstrap":
        raise
    _BOOTSTRAP_IMPORT_ERROR: ModuleNotFoundError | None = exc

    def run_agent_marketplace(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError(
            "The installed AgentCore wheel does not provide Marketplace bootstrap support"
        ) from _BOOTSTRAP_IMPORT_ERROR
else:
    _BOOTSTRAP_IMPORT_ERROR = None


try:
    from shared.secrets.env_provider import EnvProvider
except ModuleNotFoundError as exc:  # AgentCore 1.0.0 / 1.0.1 compatibility
    if exc.name != "shared.secrets.env_provider":
        raise

    class EnvProvider(SecretProvider):  # type: ignore[no-redef]
        """Minimal process-environment provider for AgentCore 1.0.0."""

        def __init__(self, namespace: str = "", agent_name: str = "") -> None:
            self._namespace = namespace
            self._agent_name = agent_name

        def get(self, key: str, default: str | None = None) -> str | None:
            return os.environ.get(key, default)


from src.graph.graph import Graph

_NAMESPACE = "cmn"
_AGENT_NAME = "CMN-C2-226"
_PROVIDER_AGENT_NAME = "cmn_c2_226"
_INVALID_INPUT_OUTPUT = "The request was rejected. Marketplace input must be a single JSON object with a non-empty 'response_text' field, and must stay within this agent's documented input-size limits."


class _NoSecretsProvider(EnvProvider):  # type: ignore[misc]
    """Deny access to all runner- or process-provided secrets."""

    def __init__(self) -> None:
        super().__init__(namespace=_NAMESPACE, agent_name=_PROVIDER_AGENT_NAME)

    def get(self, key: str, default: str | None = None) -> str | None:
        del key
        return default


class MarketplaceGraph(Graph):
    """Marketplace boundary for the deterministic QA-audit graph."""

    def invoke(
        self,
        user_input: str,
        session_id: str = "",
        ctx: InvocationContext | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Runner-owned conversation history and future context keys are untrusted.
        del input_context
        marketplace_ctx = replace(ctx, hitl_allowed=False) if ctx is not None else None
        result = super().invoke(
            user_input,
            session_id=session_id,
            ctx=marketplace_ctx,
            input_context={},
        )
        if not result.get("output") and result.get("status") not in (
            AgentStatus.SUCCESS,
            AgentStatus.SUCCESS.value,
        ):
            # Never reflect the rejected input or error log into Marketplace output.
            result["output"] = _INVALID_INPUT_OUTPUT
        return result

    def provision_secrets(self, provider: SecretProvider) -> None:
        # This deterministic graph declares and consumes no secrets. Ignore the
        # runner's broader provider and bind a provider that exposes nothing.
        del provider
        super().provision_secrets(_NoSecretsProvider())


def main() -> None:
    run_agent_marketplace(
        MarketplaceGraph,
        agent_name=_AGENT_NAME,
        namespace=_NAMESPACE,
        config=load_agent_config(Path(__file__).resolve().parent),
    )


if __name__ == "__main__":
    main()
