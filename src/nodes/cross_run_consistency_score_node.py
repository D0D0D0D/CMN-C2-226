"""AgentCore Platform v1.0 — CMN-C2-226 inner node 5: CrossRunConsistencyScore (③).

Measures semantic variance across multiple responses to the same query (batch
mode). In realtime mode there is a single response, so this node is a no-op
pass-through (consistency_score=1.0, divergence_details={}) per docs/02 (F-03).
"""

from __future__ import annotations

from itertools import combinations
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.text_analysis import jaccard


class CrossRunConsistencyScoreNode(FunctionNode):
    """③ Score cross-run consistency via pairwise lexical similarity (batch only)."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        # S-4: at least one domain event per node — framework の監査契約
        emit_trace_event(
            "cross_run_consistency_scored",
            {"mode": state.get("mode", "batch")},
            state,
        )

        if state.get("status") == AgentStatus.ERROR:
            return {}

        mode = state.get("mode", "batch")
        if mode == "realtime":
            return {
                "consistency_score": 1.0,
                "divergence_details": {"mode": "realtime", "note": "single response — consistency not evaluated"},
                "status": AgentStatus.SUCCESS.value,
            }

        texts = [state.get("response_text", "") or ""]
        texts += [s for s in (state.get("cross_run_samples") or []) if isinstance(s, str) and s]
        texts = [t for t in texts if t]

        if len(texts) < 2:
            return {
                "consistency_score": 1.0,
                "divergence_details": {"mode": "batch", "n_samples": len(texts),
                                       "note": "fewer than 2 samples — nothing to compare"},
                "status": AgentStatus.SUCCESS.value,
            }

        sims = [jaccard(a, b) for a, b in combinations(texts, 2)]
        mean_sim = sum(sims) / len(sims)
        min_sim = min(sims)

        return {
            "consistency_score": round(mean_sim, 3),
            "divergence_details": {
                "mode": "batch",
                "n_samples": len(texts),
                "mean_pair_similarity": round(mean_sim, 3),
                "min_pair_similarity": round(min_sim, 3),
            },
            "status": AgentStatus.SUCCESS.value,
        }
