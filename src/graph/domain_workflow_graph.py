"""AgentCore Platform v1.0 — CMN-C2-226 inner domain workflow graph.

Linear 6-node QA-audit pipeline, instantiated by QAAuditGraphNode.get_subgraph()
in graph.py. Inherits BaseGraph for a fully custom topology.

  START -> response_parse -> context_align -> citation_consistency_check
        -> instruction_drift_check -> cross_run_consistency_score
        -> qa_report_format -> END
"""

from __future__ import annotations

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_status import AgentStatus

from src.nodes.response_parse_node import ResponseParseNode
from src.nodes.context_align_node import ContextAlignNode
from src.nodes.citation_consistency_check_node import CitationConsistencyCheckNode
from src.nodes.instruction_drift_check_node import InstructionDriftCheckNode
from src.nodes.cross_run_consistency_score_node import CrossRunConsistencyScoreNode
from src.nodes.qa_report_format_node import QAReportFormatNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner QA-audit workflow (citation consistency, instruction drift, cross-run)."""

    @property
    def name(self) -> str:
        return "qa_audit_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config for the inner workflow.
        return None

    def register_nodes(self) -> None:
        # No super() — BaseGraph.register_nodes() is abstract.
        self._nodes["response_parse"] = ResponseParseNode()
        self._nodes["context_align"] = ContextAlignNode()
        self._nodes["citation_consistency_check"] = CitationConsistencyCheckNode()
        self._nodes["instruction_drift_check"] = InstructionDriftCheckNode()
        self._nodes["cross_run_consistency_score"] = CrossRunConsistencyScoreNode()
        self._nodes["qa_report_format"] = QAReportFormatNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "response_parse")
        self._sg.add_edge("response_parse", "context_align")
        self._sg.add_edge("context_align", "citation_consistency_check")
        self._sg.add_edge("citation_consistency_check", "instruction_drift_check")
        self._sg.add_edge("instruction_drift_check", "cross_run_consistency_score")
        self._sg.add_edge("cross_run_consistency_score", "qa_report_format")
        self._sg.add_edge("qa_report_format", END)

    def route(self, state) -> str:
        # Linear topology — route() is required by the ABC but never invoked
        # (no add_conditional_edges). Defensive default kept for completeness.
        return END if state.get("status") == AgentStatus.ERROR.value else "qa_report_format"

    def get_output(self, state) -> dict:
        return {
            "qa_report": state.get("qa_report", {}),
            "output": state.get("qa_report", {}),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "error_log": state.get("error_log", []),
        }
