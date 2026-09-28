"""AgentCore Platform v1.0 — CMN-C2-226 inner node 3: CitationConsistencyCheck (①).

Citation integrity is the moat: response citations are matched DETERMINISTICALLY
against the retrieved source chunks — no LLM-as-judge, so no self-reference risk
and no per-audit LLM cost. World-knowledge factuality (④) is out of scope.
"""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.text_analysis import overlap_ratio, extract_citations

SUPPORT_THRESHOLD = 0.5


def _chunk_lookup(chunks: list) -> dict:
    """Index chunks by chunk_id and by 1-based position string."""
    by_key: dict[str, dict] = {}
    for idx, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            continue
        by_key[str(idx)] = chunk
        cid = str(chunk.get("chunk_id", "")).strip()
        if cid:
            by_key[cid] = chunk
    return by_key


class CitationConsistencyCheckNode(FunctionNode):
    """① Verify each citation in the response is backed by the cited source chunk."""

    # S-1: declared explicitly by design, not inherited implicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        if state.get("status") == AgentStatus.ERROR:
            return {}

        claims = state.get("claims") or []
        chunks = state.get("retrieved_context") or []
        lookup = _chunk_lookup(chunks)

        findings: list[dict] = []
        total = 0
        supported = 0

        for i, claim in enumerate(claims):
            markers = extract_citations(claim)
            for marker in markers:
                total += 1
                chunk = lookup.get(str(marker))
                if chunk is None:
                    findings.append({
                        "type": "missing_source",
                        "severity": "high",
                        "claim_index": i,
                        "citation": marker,
                        "detail": f"citation [{marker}] does not resolve to any retrieved chunk",
                    })
                    continue
                ratio = overlap_ratio(claim, chunk.get("text", "") or "")
                if ratio >= SUPPORT_THRESHOLD:
                    supported += 1
                else:
                    findings.append({
                        "type": "unsupported_citation",
                        "severity": "high",
                        "claim_index": i,
                        "citation": marker,
                        "support_ratio": round(ratio, 3),
                        "detail": f"claim is not supported by cited chunk [{marker}] (overlap {ratio:.2f})",
                    })

        # Claims that assert something but carry no citation and align to no source.
        claim_map = state.get("claim_to_source_map") or {}
        for i, claim in enumerate(claims):
            if extract_citations(claim):
                continue
            if not (claim_map.get(str(i)) or []):
                if len(claim.split()) >= 4:  # ignore trivially short fragments
                    findings.append({
                        "type": "uncited_claim",
                        "severity": "low",
                        "claim_index": i,
                        "detail": "assertive claim has no citation and no aligned source chunk",
                    })

        # When the response carries explicit citations, score = supported / total.
        # When it carries NONE, an assertive-but-uncited response demonstrates no
        # citation integrity → 0.0 if any finding exists, else 1.0 (vacuously clean).
        # (F-02: the old 0.5 fallback over-scored uncited-only responses.)
        citation_score = (supported / total) if total else (0.0 if findings else 1.0)

        emit_trace_event(
            "citation_consistency_checked",
            {"total_citations": total, "supported": supported, "findings": len(findings)},
            state,
        )

        return {
            "citation_findings": findings,
            "citation_score": round(citation_score, 3),
            "status": AgentStatus.SUCCESS.value,
        }
