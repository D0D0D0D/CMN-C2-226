"""AgentCore Platform v1.0 — CMN-C2-226 inner node 2: ContextAlign."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.text_analysis import overlap_ratio

# A claim is considered "supported by" a chunk when this fraction of its content
# tokens appears in the chunk. Deterministic; no LLM.
ALIGN_THRESHOLD = 0.5


class ContextAlignNode(FunctionNode):
    """Map each parsed claim to the RAG source chunks that lexically support it."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        # S-4: at least one domain event per node — framework の監査契約
        emit_trace_event(
            "context_align_computed",
            {"claims": len(state.get("claims") or []), "chunks": len(state.get("retrieved_context") or [])},
            state,
        )

        if state.get("status") == AgentStatus.ERROR:
            return {}

        claims = state.get("claims") or []
        chunks = state.get("retrieved_context") or []

        claim_to_source: dict[str, list] = {}
        for i, claim in enumerate(claims):
            matched = []
            for pos, chunk in enumerate(chunks, start=1):
                if not isinstance(chunk, dict):
                    continue
                # Fall back to the 1-based position id when chunk_id is absent so
                # position-style citations (e.g. [1]) still align (F-03).
                chunk_id = str(chunk.get("chunk_id", "")).strip() or str(pos)
                text = chunk.get("text", "") or ""
                if overlap_ratio(claim, text) >= ALIGN_THRESHOLD:
                    matched.append(chunk_id)
            claim_to_source[str(i)] = matched

        return {
            "claim_to_source_map": claim_to_source,
            "status": AgentStatus.SUCCESS.value,
        }
