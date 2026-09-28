"""AgentCore Platform v1.0 — CMN-C2-226 State schema."""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects cause silent
# corruption.  Extend AgentState with agent-specific fields only.  Do NOT add
# credentials, secrets, or Pydantic models.
#
# CMN-C2-226 audits a deployed RAG agent's response for RAG-context integrity:
#   citation consistency, instruction drift, cross-run consistency.
# World-knowledge factuality is intentionally OUT OF SCOPE (LLM-as-judge
# self-reference) — see docs/02_design.md.

from __future__ import annotations

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Flat TypedDict for the QA-audit pipeline.

    Shared fields (user_input, status, session_id, node_history, error_log, ...)
    are inherited from AgentState. Only audit-specific fields are added below.
    All values are JSON-serializable primitives / list / dict (msgpack-safe).
    """

    # Audit inputs (parsed from the JSON payload carried in user_input)
    response_text: str          # the audited RAG agent's response
    user_query: str             # the original user query
    system_prompt: str          # the audited agent's system prompt
    constraints: list           # constraint rules (disclaimer/forbidden/required)
    retrieved_context: list     # RAG source chunks: {chunk_id,text,source_url,score}
    cross_run_samples: list     # other responses to the same query (batch only)
    mode: str                   # "realtime" | "batch"

    # Intermediate findings
    claims: list                # parsed claim units from response_text
    citations: list             # extracted citation markers
    claim_to_source_map: dict   # claim index -> [chunk_id]
    citation_findings: list     # citation-consistency findings
    citation_score: float       # citation-consistency score (0.0-1.0)
    drift_findings: list         # instruction-drift findings
    consistency_score: float    # cross-run consistency score (0.0-1.0)
    divergence_details: dict    # cross-run divergence details

    # Output
    qa_report: dict             # integrated QA report (JSON)
