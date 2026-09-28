# CMN-C2-226 — Unit tests for QA-audit nodes

import inspect

import pytest

from framework.schemas.agent_status import AgentStatus

from src.nodes.pre_process_node import PreProcessNode
from src.nodes.response_parse_node import ResponseParseNode
from src.nodes.context_align_node import ContextAlignNode
from src.nodes.citation_consistency_check_node import CitationConsistencyCheckNode
from src.nodes.instruction_drift_check_node import InstructionDriftCheckNode
from src.nodes.cross_run_consistency_score_node import CrossRunConsistencyScoreNode
from src.nodes.qa_report_format_node import QAReportFormatNode
from src.nodes.post_process_node import PostProcessNode
from src.services import text_analysis as ta


def _payload_state(**over):
    import json
    payload = {
        "user_query": "q",
        "response_text": "Refund window is 30 days [1]. Returns are free [2].",
        "system_prompt": "Always disclaim.",
        "constraints": [{"type": "disclaimer_required"}],
        "retrieved_context": [
            {"chunk_id": "1", "text": "Refund within 30 days of purchase.", "source_url": "u", "score": 0.9},
            {"chunk_id": "2", "text": "Shipping fees are non-refundable.", "source_url": "u", "score": 0.6},
        ],
        "cross_run_samples": [],
        "mode": "batch",
    }
    payload.update(over)
    return {"user_input": json.dumps(payload), "node_history": [], "error_log": []}


class TestTextAnalysis:
    def test_jaccard_identical(self):
        assert ta.jaccard("refund within 30 days", "refund within 30 days") == 1.0

    def test_jaccard_disjoint(self):
        assert ta.jaccard("apple banana", "carrot delta") == 0.0

    def test_extract_citations(self):
        assert ta.extract_citations("a [1] b [chunk_2]") == ["1", "chunk_2"]

    def test_split_claims(self):
        assert len(ta.split_claims("One sentence. Two sentence!")) == 2

    def test_overlap_ratio(self):
        assert ta.overlap_ratio("refund days", "refund within 30 days") == pytest.approx(1.0)


class TestPreProcessNode:
    def setup_method(self):
        self.node = PreProcessNode()

    def test_valid_payload(self):
        out = self.node.execute(_payload_state())
        assert out["status"] == AgentStatus.SUCCESS
        assert "validated_input" in out and out["mode"] == "batch"

    def test_empty_input(self):
        out = self.node.execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR

    def test_invalid_json(self):
        out = self.node.execute({"user_input": "not-json"})
        assert out["status"] == AgentStatus.ERROR

    def test_missing_response_text(self):
        import json
        out = self.node.execute({"user_input": json.dumps({"user_query": "x"})})
        assert out["status"] == AgentStatus.ERROR

    def test_size_gate_rejects_too_many_samples(self):
        from framework.errors import SecurityViolationError
        st = _payload_state(cross_run_samples=["s"] * 25)
        with pytest.raises(SecurityViolationError):
            self.node._extra_security_gate_input(st)

    def test_size_gate_passes_within_limits(self):
        st = _payload_state(cross_run_samples=["s", "t"])
        assert self.node._extra_security_gate_input(st) is st

    def test_mode_normalized_in_validated_input(self):
        import json
        out = self.node.execute(_payload_state(mode="Realtime; garbage"))
        assert out["mode"] == "batch"
        assert json.loads(out["validated_input"])["mode"] == "batch"


class TestResponseParseNode:
    def test_parse_claims_and_citations(self):
        out = ResponseParseNode().execute(_payload_state())
        assert out["status"] == AgentStatus.SUCCESS
        assert len(out["claims"]) == 2
        assert out["citations"] == ["1", "2"]
        assert out["response_text"].startswith("Refund window")


class TestContextAlignNode:
    def test_alignment_maps_claims_to_sources(self):
        parsed = ResponseParseNode().execute(_payload_state())
        out = ContextAlignNode().execute({**parsed})
        assert out["status"] == AgentStatus.SUCCESS
        # claim 0 ("Refund window is 30 days") aligns to chunk 1
        assert "1" in out["claim_to_source_map"]["0"]

    def test_short_circuit_on_error(self):
        assert ContextAlignNode().execute({"status": AgentStatus.ERROR}) == {}


class TestCitationConsistencyCheckNode:
    def test_detects_unsupported_citation(self):
        parsed = ResponseParseNode().execute(_payload_state())
        aligned = ContextAlignNode().execute({**parsed})
        out = CitationConsistencyCheckNode().execute({**parsed, **aligned})
        assert out["status"] == AgentStatus.SUCCESS
        types = {f["type"] for f in out["citation_findings"]}
        assert "unsupported_citation" in types  # [2] claim not supported by shipping chunk
        assert 0.0 <= out["citation_score"] <= 1.0

    def test_missing_source_citation(self):
        st = _payload_state(response_text="Claim about widgets [9].")
        parsed = ResponseParseNode().execute(st)
        out = CitationConsistencyCheckNode().execute({**parsed, "claim_to_source_map": {}})
        assert any(f["type"] == "missing_source" for f in out["citation_findings"])

    def test_uncited_only_scores_zero(self):
        # No explicit citations + assertive uncited claim -> score 0.0, not 0.5 (F-02).
        st = _payload_state(response_text="Our product cures every disease completely.",
                            retrieved_context=[])
        parsed = ResponseParseNode().execute(st)
        out = CitationConsistencyCheckNode().execute({**parsed, "claim_to_source_map": {"0": []}})
        assert out["citation_findings"]  # has an uncited_claim finding
        assert out["citation_score"] == 0.0


class TestInstructionDriftCheckNode:
    def test_missing_disclaimer_flagged(self):
        st = _payload_state(response_text="Refund in 30 days [1].",
                            constraints=[{"type": "disclaimer_required"}])
        parsed = ResponseParseNode().execute(st)
        out = InstructionDriftCheckNode().execute({**parsed})
        assert any(f["type"] == "disclaimer_required" for f in out["drift_findings"])

    def test_forbidden_phrase_flagged(self):
        st = _payload_state(response_text="This is guaranteed to work. Not legal advice.",
                            constraints=[{"type": "forbidden_phrase", "value": "guaranteed"}])
        parsed = ResponseParseNode().execute(st)
        out = InstructionDriftCheckNode().execute({**parsed})
        assert any(f["type"] == "forbidden_phrase" for f in out["drift_findings"])

    def test_compliant_response_no_findings(self):
        st = _payload_state(response_text="Refund in 30 days [1]. This is not legal advice.",
                            constraints=[{"type": "disclaimer_required"}])
        parsed = ResponseParseNode().execute(st)
        out = InstructionDriftCheckNode().execute({**parsed})
        assert out["drift_findings"] == []


class TestCrossRunConsistencyScoreNode:
    def test_realtime_passthrough(self):
        out = CrossRunConsistencyScoreNode().execute({"mode": "realtime", "response_text": "x"})
        assert out["consistency_score"] == 1.0
        assert out["divergence_details"]["mode"] == "realtime"

    def test_batch_scores_divergence(self):
        st = {"mode": "batch", "response_text": "refund in 30 days",
              "cross_run_samples": ["refund in 30 days", "refund in 7 days only"]}
        out = CrossRunConsistencyScoreNode().execute(st)
        assert 0.0 <= out["consistency_score"] <= 1.0
        assert out["divergence_details"]["n_samples"] == 3


class TestQAReportFormatNode:
    def test_overall_fail_on_high(self):
        st = {"citation_findings": [{"severity": "high", "type": "unsupported_citation"}],
              "drift_findings": [], "citation_score": 0.5, "consistency_score": 1.0,
              "divergence_details": {}, "mode": "batch"}
        out = QAReportFormatNode().execute(st)
        assert out["qa_report"]["overall"] == "fail"
        assert out["qa_report"]["summary"]["high"] == 1

    def test_error_state_produces_error_report(self):
        out = QAReportFormatNode().execute({"status": AgentStatus.ERROR, "error_log": ["x"]})
        assert out["qa_report"]["overall"] == "error"


class TestPostProcessNode:
    def test_formats_markdown(self):
        st = {"qa_report": {"overall": "pass", "mode": "batch",
                            "citation": {"score": 1.0}, "consistency": {"score": 1.0},
                            "summary": {"total_findings": 0, "high": 0, "medium": 0, "low": 0}}}
        out = PostProcessNode().execute(st)
        assert out["status"] == AgentStatus.SUCCESS
        assert "QA Report" in out["formatted_output"]


class TestNodeContract:
    """Node contract: nodes implement execute(self, state), not _invoke_impl."""

    @pytest.mark.parametrize("node_cls", [
        PreProcessNode, ResponseParseNode, ContextAlignNode,
        CitationConsistencyCheckNode, InstructionDriftCheckNode,
        CrossRunConsistencyScoreNode, QAReportFormatNode, PostProcessNode,
    ])
    def test_execute_signature(self, node_cls):
        assert hasattr(node_cls, "execute")
        params = list(inspect.signature(node_cls.execute).parameters.keys())
        assert params[1] == "state"
        assert "_invoke_impl" not in node_cls.__dict__
