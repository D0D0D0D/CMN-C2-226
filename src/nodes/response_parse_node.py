"""AgentCore Platform v1.0 — CMN-C2-226 inner node 1: ResponseParse."""

from __future__ import annotations

import json
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.text_analysis import split_claims, extract_citations


class ResponseParseNode(FunctionNode):
    """Parse the JSON audit payload (carried in user_input) into typed fields,
    then decompose the audited response into claim units and citation markers."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        # S-4: at least one domain event per node — framework の監査契約
        emit_trace_event(
            "response_parse_started",
            {"input_chars": len(state.get("validated_input") or state.get("user_input") or "")},
            state,
        )

        # Prefer the canonical validated_input prepared by pre_process; fall back
        # to user_input (the inner graph receives it as user_input via extract_input) (F-04).
        raw = state.get("validated_input") or state.get("user_input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except (ValueError, TypeError):
            payload = {}

        response_text = payload.get("response_text") or ""
        if not isinstance(payload, dict) or not response_text:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ResponseParseNode: missing or invalid response payload"],
            }

        claims = split_claims(response_text)
        citations = extract_citations(response_text)

        return {
            "response_text": response_text,
            "user_query": payload.get("user_query", ""),
            "system_prompt": payload.get("system_prompt", ""),
            "constraints": payload.get("constraints") or [],
            "retrieved_context": payload.get("retrieved_context") or [],
            "cross_run_samples": payload.get("cross_run_samples") or [],
            "mode": payload.get("mode", "batch"),
            "claims": claims,
            "citations": citations,
            "status": AgentStatus.SUCCESS.value,
        }
