"""AgentCore Platform v1.0 — CMN-C2-226 outer graph (Cat 2).

Fixed 5-node backbone (AgentBaseGraph). The `main` slot holds a GraphNode that
wraps the inner DomainWorkflowGraph (the 6-node QA-audit pipeline). The backbone
wiring (add_edges / route) is owned by the framework and is NOT overridden.

  START -> initialize -> pre_process -> main -> {route} -> post_process -> finalize -> END
                                          |__ QAAuditGraphNode -> DomainWorkflowGraph
"""

from __future__ import annotations

from typing import ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState

from src.nodes.pre_process_node import PreProcessNode
from src.nodes.post_process_node import PostProcessNode
from src.schemas.state import State


class QAAuditGraphNode(GraphNode):
    """`main` slot — runs the inner QA-audit workflow as a subgraph."""

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def get_subgraph(self):
        from src.graph.domain_workflow_graph import DomainWorkflowGraph
        return DomainWorkflowGraph()

    def extract_input(self, state: AgentState) -> str:
        # The canonical JSON audit payload prepared by pre_process.
        return state.get("validated_input", state.get("user_input", ""))

    def merge_output(self, state: AgentState, sub_result: dict) -> dict:
        merged = {
            "qa_report": sub_result.get("qa_report", {}),
            "result": sub_result.get("qa_report", {}),
            "status": sub_result.get("status"),
        }
        if sub_result.get("error_log"):
            merged["error_log"] = sub_result["error_log"]
        return merged


class Graph(AgentBaseGraph):
    """CMN-C2-226 outer graph — Agent Output Hallucination & Quality Anomaly Detection."""

    @property
    def name(self) -> str:
        return "cmn_c2_226"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = QAAuditGraphNode()
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() / route() are NOT overridden — backbone wiring belongs to L1.

    def get_output(self, state) -> dict:
        # Surface the structured QA report alongside the standard envelope.
        return {
            "output": state.get("formatted_output") or state.get("qa_report") or state.get("result"),
            "qa_report": state.get("qa_report", {}),
            "status": state.get("status"),
            "error_log": state.get("error_log", []),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
