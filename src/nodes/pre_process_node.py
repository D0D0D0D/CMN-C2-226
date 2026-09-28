"""AgentCore Platform v1.0 — CMN-C2-226 pre_process (outer backbone)."""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Read input via state["user_input"] (the JSON audit payload, PII-masked by S-2)
#  - S-2 size limits enforced in _extra_security_gate_input (F-02)

from __future__ import annotations

import json
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.errors import SecurityViolationError
from shared.utils.audit_logger import emit_trace_event

# Input-size ceilings (F-02). Override-able by a deployment via config/config.yaml
# (limits:) — surfaced here as module defaults for the v1 reference template.
MAX_CROSS_RUN_SAMPLES = 20
MAX_SAMPLE_CHARS = 8000
MAX_RETRIEVED_CHUNKS = 50
MAX_RESPONSE_CHARS = 20000


class PreProcessNode(FunctionNode):
    """Validate the audit payload and normalize it before the main workflow.

    The audit payload (response_text, retrieved_context, system_prompt,
    constraints, cross_run_samples, mode) is carried as a JSON string in
    user_input so the framework's S-2 PII scan masks it uniformly across the
    response and its sources (privacy-positive; keeps citation matching consistent).
    """

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def _extra_security_gate_input(self, state: dict) -> dict:
        """S-2 domain extension — reject oversized payloads (DoS / cost guard)."""
        raw = state.get("user_input", "")
        if not isinstance(raw, str) or not raw.strip():
            return state
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            # Structural validity is handled in execute(); the gate only guards size.
            return state
        if not isinstance(payload, dict):
            return state

        samples = payload.get("cross_run_samples") or []
        if isinstance(samples, list):
            if len(samples) > MAX_CROSS_RUN_SAMPLES:
                raise SecurityViolationError(
                    f"PreProcessNode: cross_run_samples exceeds limit "
                    f"({len(samples)} > {MAX_CROSS_RUN_SAMPLES})"
                )
            for s in samples:
                if isinstance(s, str) and len(s) > MAX_SAMPLE_CHARS:
                    raise SecurityViolationError(
                        f"PreProcessNode: a cross_run_sample exceeds {MAX_SAMPLE_CHARS} chars"
                    )

        chunks = payload.get("retrieved_context") or []
        if isinstance(chunks, list) and len(chunks) > MAX_RETRIEVED_CHUNKS:
            raise SecurityViolationError(
                f"PreProcessNode: retrieved_context exceeds limit "
                f"({len(chunks)} > {MAX_RETRIEVED_CHUNKS})"
            )

        resp = payload.get("response_text") or ""
        if isinstance(resp, str) and len(resp) > MAX_RESPONSE_CHARS:
            raise SecurityViolationError(
                f"PreProcessNode: response_text exceeds {MAX_RESPONSE_CHARS} chars"
            )
        return state

    def execute(self, state: dict) -> dict:
        # S-4: at least one domain event per node — framework の監査契約
        emit_trace_event(
            "pre_process_validated",
            {"input_chars": len(state.get("user_input", "") or "")},
            state,
        )

        raw = state.get("user_input", "")
        if not raw or not raw.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: empty audit payload (user_input)"],
            }

        try:
            payload = json.loads(raw)
        except (ValueError, TypeError) as e:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"PreProcessNode: audit payload is not valid JSON: {e}"],
            }
        if not isinstance(payload, dict) or not payload.get("response_text"):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: payload must be a JSON object with 'response_text'"],
            }

        mode = payload.get("mode", "batch")
        if mode not in ("realtime", "batch"):
            mode = "batch"
        payload["mode"] = mode  # write back so downstream nodes see the clamped value (M2)

        # Canonical JSON passed down to the inner workflow graph via extract_input().
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return {
            "validated_input": canonical,
            "mode": mode,
            "status": AgentStatus.SUCCESS.value,
        }
