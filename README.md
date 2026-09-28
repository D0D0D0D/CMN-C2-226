# CMN-C2-226 — Agent Output Hallucination & Quality Anomaly Detection Agent

> **Category**: Cat 2 (domain workflow)
> **Industry**: CMN

## Overview

This template audits the answer a retrieval-augmented generation (RAG) agent produced, using the
material that agent was given. It splits the response into claims and checks three things: whether
each cited claim is actually supported by the supplied source chunks, whether stated response
constraints were followed, and — when several answers to the same question are supplied — how far
they diverge from one another. It returns a structured QA report as JSON plus a short Markdown
summary.

It suits work where an answer already exists and the question is whether to trust it: a developer
gating RAG responses before release, a prompt operator checking that a required disclaimer or a
prohibited phrase rule held, or a quality reviewer comparing repeated answers to the same question
to see how stable the system is.

**The scope is deliberately narrow, and the narrowness is the point.** The audit is *relative to
the sources you pass in*. It answers "is this claim backed by the context this agent retrieved?"
— never "is this claim true in the world." There is no external lookup and no second model asked
to judge the first, because an LLM grading another LLM's factuality without a source of truth
mostly reproduces the same blind spots. If you pass no `retrieved_context`, there is nothing to
check a citation against.

The analysis is rule-based and deterministic: the same payload yields the same report. The
optional LLM assist for instruction-drift detection is disabled, so this template needs no model
credentials and makes no external calls.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Integration

Provide:

- an AgentCore runtime;
- caller authentication in front of the entry adapter (see *Input*).

No language-model client and no secrets are required — `config/agent.yaml` declares
`requires.secrets: []` and the audit path is entirely rule-based.

`config/config.yaml` records the intended deployment settings — `default_mode`, the `limits:`
block and `llm_assist.enabled`. Note that **no code reads it today**: the size ceilings are
module constants in `src/nodes/pre_process_node.py`, the mode default is the payload fallback
`"batch"`, and the LLM assist is not implemented. Treat the file as the place to declare those
values when you wire them up, not as a live control surface (see *Security and Limitations*).

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent is designed to run on the platform, which supplies the caller identity and the deployment configuration. Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Supplied by the platform's own package registry at build time. It is not published on public PyPI, so `pip install -e .` alone does not fetch it. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run on AGENTIC STAR, and the agent does not fall back to a degraded
mode when it is absent. The standalone server in `src/api/server.py` does start without the
platform: it compiles the graph and serves `/health` and `/invoke`. Because the audit needs no
model and no secrets, an authenticated request against a bare `uvicorn src.api.server:app` does
produce a real QA report — but it runs with the in-code defaults rather than any deployment
configuration, and with only the entry adapter standing in for platform authentication. The test
suite runs without a platform connection.

## Input

`POST /invoke` takes a JSON body with `input` and an optional `session_id`. **`input` is itself a
JSON string** holding the whole audit payload — it is carried as a string so the framework's input
scan sees the response and its sources uniformly.

| Payload field | Meaning |
|---|---|
| `response_text` | The agent answer under audit |
| `retrieved_context` | The source chunks that answer was produced from (`chunk_id`, `text`, `source_url`, `score`) |
| `user_query` | The question that was asked |
| `system_prompt` | The instructions the audited agent was given |
| `constraints` | Response rules to check, e.g. `{"type": "disclaimer_required"}` |
| `cross_run_samples` | Other answers to the same question, for the consistency check |
| `mode` | `batch` (default) evaluates cross-run consistency; `realtime` skips it |

Callers must be authenticated. Trust stamped by verified upstream middleware is used as-is;
otherwise, when `INVOKE_AUTH_TOKEN` is set on the server environment, a matching
`Authorization: Bearer` header promotes the caller to `VERIFIED_EXTERNAL`. A caller that is
neither middleware-verified nor token-authenticated is rejected with **401**, a wrong token is
**401**, and a verified caller below `VERIFIED_EXTERNAL` is **403**.

```bash
curl -X POST http://127.0.0.1:8000/invoke \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${INVOKE_AUTH_TOKEN}" \
  -d '{
    "input": "{\"user_query\":\"What is the refund window?\",\"response_text\":\"A refund may be requested within 30 days of purchase [1]. This is not legal advice.\",\"system_prompt\":\"Always include a disclaimer.\",\"constraints\":[{\"type\":\"disclaimer_required\"}],\"retrieved_context\":[{\"chunk_id\":\"1\",\"text\":\"Customers may request a refund within 30 days of purchase.\",\"source_url\":\"kb://r\",\"score\":0.9}],\"cross_run_samples\":[],\"mode\":\"realtime\"}",
    "session_id": "example-session"
  }'
```

`GET /health` returns a liveness response and takes no authentication.

Oversized payloads are rejected before the audit runs, as a cost and denial-of-service guard: at
most 20 `cross_run_samples`, 8,000 characters per sample, 50 `retrieved_context` chunks, and
20,000 characters of `response_text`.

## Output

The standard AgentCore envelope is preserved. `output` carries the Markdown summary, and
`qa_report` carries the structured report, alongside `status`, `error_log`, `trace_id`,
`correlation_id` and `node_history`.

`qa_report` records the citation score and its findings, the instruction-drift findings, the
cross-run consistency score, a severity roll-up, and an `overall` verdict. It also states its own
scope in the report itself, so a downstream consumer cannot mistake it for a factuality judgment.

```json
{
  "output": "# QA Report — CMN-C2-226\n- Overall: **pass**\n- Mode: realtime\n- Citation score: 1.0\n- Consistency score: 1.0\n- Findings: 0 (high=0, medium=0, low=0)\n\n_Scope: RAG-context integrity only. World-knowledge factuality is out of scope._",
  "qa_report": {
    "template_id": "CMN-C2-226",
    "scope": "RAG-context integrity: citation consistency, instruction drift, cross-run consistency",
    "out_of_scope": "world-knowledge factuality",
    "mode": "realtime",
    "citation": {"score": 1.0, "findings": []},
    "instruction_drift": {"findings": []},
    "consistency": {
      "score": 1.0,
      "details": {"mode": "realtime", "note": "single response — consistency not evaluated"}
    },
    "summary": {"total_findings": 0, "high": 0, "medium": 0, "low": 0},
    "overall": "pass"
  },
  "status": "success",
  "error_log": []
}
```

Values above are illustrative; real output depends on the payload supplied.

## Security and Limitations

Authentication is enforced at the entry adapter, which rejects an unauthenticated or
insufficiently trusted caller with 401/403 before the graph runs. The audit nodes themselves
declare the permissive trust level, because by that point the payload is caller-supplied data
being analysed rather than a privileged operation — **which means the entry adapter is the only
access control.** If you serve this graph through a different adapter, carry the same check
across.

Payload size is capped on the way in, and the formatted report is re-scanned for credential
patterns on the way out; a match is raised as a security violation rather than returned, so a
secret pasted into the audited response cannot leave through the QA report.

Four limits are worth knowing before deploying this template as-is:

- **`config/config.yaml` is inert.** Nothing in `src/` reads the graph configuration. The size
  ceilings are constants in `src/nodes/pre_process_node.py`, `default_mode` is the hardcoded
  `"batch"` fallback where the payload omits `mode`, and `llm_assist` has no implementation
  behind it. Changing the file changes nothing until the reads are wired up; change the
  constants, or wire the configuration through, before relying on a per-deployment value.
- **A citation check is a support check, not a truth check.** A claim passes when the supplied
  chunks lexically support it. If the sources themselves are wrong, or the same wording appears
  in an unrelated chunk, the claim still passes.
- **`realtime` mode does not evaluate consistency.** It returns a consistency score of `1.0`
  because there is nothing to compare, not because the answer was found stable. Use `batch` with
  `cross_run_samples` when the score should mean something.
- **Instruction-drift detection is rule-based.** It checks the constraints you declare, in the
  form the rules understand. A constraint you did not declare is not checked, and a paraphrased
  violation may not match.

Output is machine-generated and assistive. It does not substitute for expert review, and any
decision that matters should be verified by a person against the primary sources.

## Release

- Version: 1.0.0
- Category: fixed multi-step domain workflow (Cat 2), inner subgraph pipeline
- Generation mode: `deterministic` — rule-based; no model call on the audit path
- HITL: not enabled
- Persistence: none — no checkpointer is configured
- External API clients: none

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection.

## Project Structure

```
src/          agent implementation (nodes, graphs, schemas)
tests/        unit, integration and boundary tests
config/       agent manifest and runtime configuration
docs/         design and test documentation
```

## Customising

1. Adjust the size ceilings in `src/nodes/pre_process_node.py` for your payload sizes.
2. Extend the constraint rules for the response policies your deployment enforces.
3. Decide how `mode` is chosen for your traffic — gate a single answer with `realtime`, or
   compare repeated answers with `batch`.
4. Re-run the test suite.

## Documentation

`docs/02_design.md` carries the node flow, the state schema and the security design.
`docs/03_test_spec.md` records the test specification and the verification results.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
