"""AgentCore Platform v1.0 — CMN-C2-226 inner node 4: InstructionDriftCheck (②).

Rule-based by default (v1). Verifies the audited response honours its system-prompt
constraints — disclaimer presence, forbidden phrasing, length, regex rules. The
former RegClaimCheck (regulatory-claim / disclaimer) is folded in here. An optional
LLM-assist seam (src/services/llm_client.py) is disabled by default (deterministic,
no cost). World-knowledge factuality (④) is out of scope.
"""

from __future__ import annotations

import re
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.llm_client import default_client

_GENERIC_DISCLAIMER_HINTS = (
    "disclaimer", "not financial advice", "not legal advice", "consult",
    "for informational purposes", "免責", "本情報は",
)


class InstructionDriftCheckNode(FunctionNode):
    """② Rule-based check of response compliance with system-prompt constraints."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self) -> None:
        super().__init__()
        self._llm = default_client()  # disabled in v1 (injection seam)

    def execute(self, state: dict) -> dict:
        if state.get("status") == AgentStatus.ERROR:
            return {}

        response = state.get("response_text", "") or ""
        low = response.lower()
        constraints = state.get("constraints") or []
        findings: list[dict] = []

        for rule in constraints:
            if not isinstance(rule, dict):
                continue
            rtype = rule.get("type", "")
            value = rule.get("value", "")

            if rtype in ("required_phrase", "disclaimer_required"):
                if value:
                    if str(value).lower() not in low:
                        findings.append(_finding(rtype, "high", rule,
                                                 f"required phrase not found: {value!r}"))
                elif rtype == "disclaimer_required":
                    if not any(h in low for h in _GENERIC_DISCLAIMER_HINTS):
                        findings.append(_finding(rtype, "high", rule,
                                                 "required disclaimer is missing"))

            elif rtype == "forbidden_phrase":
                if value and str(value).lower() in low:
                    findings.append(_finding(rtype, "high", rule,
                                             f"forbidden phrase present: {value!r}"))

            elif rtype == "forbidden_pattern":
                pattern = rule.get("pattern", value)
                if pattern and re.search(str(pattern), response, re.IGNORECASE):
                    findings.append(_finding(rtype, "medium", rule,
                                             f"forbidden pattern matched: {pattern!r}"))

            elif rtype == "max_length":
                try:
                    limit = int(value)
                    if len(response) > limit:
                        findings.append(_finding(rtype, "low", rule,
                                                 f"response length {len(response)} exceeds {limit}"))
                except (ValueError, TypeError):
                    pass

        emit_trace_event(
            "instruction_drift_checked",
            {"constraints": len(constraints), "findings": len(findings),
             "llm_assist": getattr(self._llm, "enabled", False)},
            state,
        )

        return {
            "drift_findings": findings,
            "status": AgentStatus.SUCCESS.value,
        }


def _finding(rtype: str, severity: str, rule: dict, detail: str) -> dict:
    return {"type": rtype, "severity": severity, "rule": rule, "detail": detail}
