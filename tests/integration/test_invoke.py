# CMN-C2-226 — Integration tests: full graph invoke

import json


from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


def _ctx():
    return InvocationContext(session_id="it", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


def _invoke(payload):
    g = Graph()
    g.compile()
    return g.invoke(json.dumps(payload), ctx=_ctx())


BASE = {
    "user_query": "What is the refund window?",
    "response_text": "Refund window is 30 days [1]. Returns are free [2]. This is not legal advice.",
    "system_prompt": "Always include a disclaimer.",
    "constraints": [{"type": "disclaimer_required"}, {"type": "forbidden_phrase", "value": "guaranteed"}],
    "retrieved_context": [
        {"chunk_id": "1", "text": "Customers may request a refund within 30 days of purchase.", "source_url": "kb://r", "score": 0.9},
        {"chunk_id": "2", "text": "Shipping fees are non-refundable.", "source_url": "kb://s", "score": 0.6},
    ],
    "cross_run_samples": ["Refund window is 30 days [1].", "You can get a refund in 30 days [1]."],
    "mode": "batch",
}


class TestInvoke:
    def test_success_returns_qa_report(self):
        out = _invoke(BASE)
        assert out["status"] == AgentStatus.SUCCESS
        report = out["qa_report"]
        assert report["template_id"] == "CMN-C2-226"
        assert "out_of_scope" in report  # scope boundary surfaced
        assert report["overall"] in ("pass", "warn", "fail")

    def test_detects_unsupported_citation(self):
        out = _invoke(BASE)
        findings = out["qa_report"]["citation"]["findings"]
        assert any(f["type"] == "unsupported_citation" for f in findings)

    def test_backbone_node_order(self):
        out = _invoke(BASE)
        assert out["node_history"] == [
            "InitializeNode", "PreProcessNode", "QAAuditGraphNode",
            "PostProcessNode", "FinalizeNode",
        ]

    def test_realtime_mode_skips_consistency(self):
        payload = {**BASE, "mode": "realtime", "cross_run_samples": []}
        out = _invoke(payload)
        assert out["status"] == AgentStatus.SUCCESS
        assert out["qa_report"]["consistency"]["details"]["mode"] == "realtime"

    def test_clean_response_passes(self):
        payload = {
            **BASE,
            "response_text": "A refund may be requested within 30 days of purchase [1]. This is not legal advice.",
            "cross_run_samples": [],
            "mode": "realtime",
        }
        out = _invoke(payload)
        assert out["qa_report"]["overall"] in ("pass", "warn")
        assert out["qa_report"]["citation"]["score"] >= 0.5

    def test_oversize_payload_rejected(self, is_error):
        payload = {**BASE, "cross_run_samples": ["s"] * 50}
        out = _invoke(payload)
        # S-2 size gate rejects -> pipeline ends in error status
        assert is_error(out["status"])

    def test_empty_response_text_errors(self, is_error):
        payload = {**BASE, "response_text": ""}
        out = _invoke(payload)
        assert is_error(out["status"])

    def test_error_surfaces_error_log(self, is_error):
        # Invalid payload must return status=ERROR AND a non-empty error_log (M1).
        out = _invoke({**BASE, "response_text": ""})
        assert is_error(out["status"])
        assert out.get("error_log"), "error_log must be surfaced to the caller on failure"

    def test_invalid_mode_clamped_to_batch(self):
        # Arbitrary mode strings must be clamped, not echoed into the report (M2).
        out = _invoke({**BASE, "mode": "Realtime; <script>", "cross_run_samples": []})
        assert out["qa_report"]["mode"] in ("batch", "realtime")
