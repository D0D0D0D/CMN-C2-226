"""AgentCore Platform v1.0 — CMN-C2-226 post_process (outer backbone)."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.errors import SecurityViolationError
from shared.utils.audit_logger import emit_trace_event
from shared.security.credential_detector import detect_credentials


class PostProcessNode(FunctionNode):
    """Render the QA report as a Markdown summary and emit a domain audit event."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def _extra_security_gate_output(self, result: dict) -> dict:
        """S-3 domain extension — defense-in-depth credential scan on the summary.

        Raise SecurityViolationError (not a generic RuntimeError) so the framework
        classifies this as a security violation for audit/alerting (F-01).
        """
        text = result.get("formatted_output", "")
        if isinstance(text, str) and text and detect_credentials(text):
            raise SecurityViolationError(
                "PostProcessNode: credential pattern detected in QA summary — output blocked"
            )
        return result

    def execute(self, state: dict) -> dict:
        qa_report = state.get("qa_report") or {}
        if not isinstance(qa_report, dict):
            qa_report = {}
        summary = qa_report.get("summary", {})
        overall = qa_report.get("overall", "unknown")
        citation_score = qa_report.get("citation", {}).get("score", "n/a")
        consistency_score = qa_report.get("consistency", {}).get("score", "n/a")

        lines = [
            "# QA Report — CMN-C2-226",
            f"- Overall: **{overall}**",
            f"- Mode: {qa_report.get('mode', 'batch')}",
            f"- Citation score: {citation_score}",
            f"- Consistency score: {consistency_score}",
            f"- Findings: {summary.get('total_findings', 0)} "
            f"(high={summary.get('high', 0)}, medium={summary.get('medium', 0)}, low={summary.get('low', 0)})",
            "",
            "_Scope: RAG-context integrity only. World-knowledge factuality is out of scope._",
        ]
        formatted = "\n".join(lines)

        emit_trace_event(
            "qa_report_generated",
            {"overall": overall, "total_findings": summary.get("total_findings", 0)},
            state,
        )

        return {
            "formatted_output": formatted,
            "status": AgentStatus.SUCCESS.value,
        }
