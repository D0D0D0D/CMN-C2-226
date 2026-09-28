"""AgentCore Platform v1.0 — CMN-C2-226 inner node 6: QAReportFormat."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

SCOPE = "RAG-context integrity: citation consistency, instruction drift, cross-run consistency"
OUT_OF_SCOPE = "world-knowledge factuality (out of scope — LLM-as-judge self-reference)"


class QAReportFormatNode(FunctionNode):
    """Integrate per-dimension findings into a single structured QA report."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        # S-4: at least one domain event per node — framework の監査契約
        emit_trace_event(
            "qa_report_formatted",
            {"prior_status": str(state.get("status", ""))},
            state,
        )

        if state.get("status") == AgentStatus.ERROR:
            # Preserve an error report so the caller still receives structured output.
            return {
                "qa_report": {
                    "template_id": "CMN-C2-226",
                    "scope": SCOPE,
                    "out_of_scope": OUT_OF_SCOPE,
                    "overall": "error",
                    "error_log": state.get("error_log", []),
                },
                "status": AgentStatus.ERROR.value,
            }

        citation_findings = state.get("citation_findings") or []
        drift_findings = state.get("drift_findings") or []
        all_findings = list(citation_findings) + list(drift_findings)

        sev = {"high": 0, "medium": 0, "low": 0}
        for f in all_findings:
            s = f.get("severity", "low")
            if s in sev:
                sev[s] += 1

        overall = "pass"
        if sev["high"] > 0:
            overall = "fail"
        elif sev["medium"] > 0:
            overall = "warn"

        qa_report = {
            "template_id": "CMN-C2-226",
            "scope": SCOPE,
            "out_of_scope": OUT_OF_SCOPE,
            "mode": state.get("mode", "batch"),
            "citation": {
                "score": state.get("citation_score", 1.0),
                "findings": citation_findings,
            },
            "instruction_drift": {
                "findings": drift_findings,
            },
            "consistency": {
                "score": state.get("consistency_score", 1.0),
                "details": state.get("divergence_details", {}),
            },
            "summary": {
                "total_findings": len(all_findings),
                "high": sev["high"],
                "medium": sev["medium"],
                "low": sev["low"],
            },
            "overall": overall,
        }

        return {
            "qa_report": qa_report,
            "result": qa_report,
            "status": AgentStatus.SUCCESS.value,
        }
