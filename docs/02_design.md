# Template Design Specification — CMN-C2-226

> Agent Output Hallucination & Quality Anomaly Detection Agent
> **Design basis**: docs/01_proposal.md
> **スコープ**: ① citation consistency ② instruction drift ③ cross-run consistency に限定。
> ④ world-knowledge factuality は LLM-as-judge の self-reference 問題によりスコープ外。

## Position in AgentCore Architecture

- **Agent Class**: `Graph`（outer graph, src/graph/graph.py）
- **L1 Base**: AgentBaseGraph（L1 直接継承。`AutonomousBaseGraph` ではない）
- **Pattern**: ChatAgent（LLM-as-judge）参照 — ただし継承は L1 framework を直接行う
- **Three-Layer Separation**:
  - State: flat TypedDict composition（Pydantic 不可 — msgpack 非互換）
  - Node: L1 inheritance（Template Method: `execute(self, state: dict) -> dict` の override のみ）
  - Graph: composition（`register_nodes()` によるノード差し替え + Cat 2 の inner GraphNode 合成）

本テンプレートは **Cat 2** であり、固定 5 ノード backbone（外側）の `main` スロットに `GraphNode` を置き、その内部に**ドメイン 6 ノードの inner workflow graph** をカプセル化する。外側 backbone は Cat 1 と同一で、ドメインの複雑性は `DomainWorkflowGraphNode.get_subgraph()` が返す inner graph に閉じる。

## Architecture Overview

### Node Configuration（外側 backbone — 固定 5 ノード）

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version / session_id / trust_level の設定 | user_input | session 初期化 | InitializeNode (default) |
| pre_process | 監査入力の検証・正規化（response_text / retrieved_context / mode の妥当性）。S-2 入力ゲート拡張で監査対象応答の PII 取扱いを確認 | 監査入力一式 | validated_input, mode | `PreProcessNode` (FunctionNode) |
| main | inner workflow graph（6 ノード）を呼び出し QA 監査を実行。`GraphNode` の no-op S-2/S-3（gating は子ノードが担う） | validated_input ほか | qa_report, status | `QAAuditGraphNode` (GraphNode) |
| post_process | qa_report の整形（JSON + markdown summary）。S-4 で domain trace event を emit、S-3 出力ゲートで credential 混入を再確認 | qa_report | formatted qa_report | `PostProcessNode` (FunctionNode) |
| finalize | response_metadata / total_time_ms の構築 | — | 完了メタ | FinalizeNode (default) |

### Inner Workflow Graph（`main` スロット内 — ドメイン 6 ノード）

`src/graph/domain_workflow_graph.py`（`DomainWorkflowGraph(BaseGraph)`、linear topology）。各ノードは `FunctionNode` を継承し `execute(self, state) -> dict` で**変更したキーのみ**を返す。

```
START → response_parse → context_align → citation_consistency_check
        → instruction_drift_check → cross_run_consistency_score → qa_report_format → END
```

| # | Node | 主要ロジック | 出力 State |
|---|------|------------|-----------|
| 1 | `ResponseParseNode` | 監査対象応答を文 / claim 単位に分解、引用マーカー抽出 | `claims[]`, `citations[]` |
| 2 | `ContextAlignNode` | 各 claim を RAG `retrieved_context` チャンクと対応付け | `claim_to_source_map` |
| 3 | `CitationConsistencyCheckNode`（①） | 応答の引用 ⇔ retrieve したソースチャンクを**決定的に**突き合わせ、裏付けのない / 矛盾する引用を検出（LLM 不要） | `citation_findings[]`, `citation_score` |
| 4 | `InstructionDriftCheckNode`（②） | `system_prompt` / `constraints`（口調・出力形式・禁止項目・disclaimer 必須等）の遵守をルールベース照合（必要時 LLM 補助）。**規制的主張・disclaimer 欠落（旧 `RegClaimCheck`）はここに統合**して照合。S-4 emit | `drift_findings[]` |
| 5 | `CrossRunConsistencyScoreNode`（③） | 同一入力の `cross_run_samples` 間の意味的分散をスコア化（batch モード時のみ有効）。**`mode="realtime"` 時は無条件 pass-through**（`cross_run_samples=[]` 前提、`consistency_score=1.0` / `divergence_details={}` を返して次ノードへ） | `consistency_score`, `divergence_details` |
| 6 | `QAReportFormatNode` | 各ノードの findings を統合し構造化 QA レポートへ整形 | `qa_report` |

> **Node Flow 改訂（7 ノード → 6 ノード）**: 旧 `HallucinationDetect`（④ 世界知識の事実性）は self-reference 問題でスコープ外として除外、旧 `RegClaimCheck`（規制的主張・disclaimer）は `InstructionDriftCheckNode`（②）に統合。この 6 ノード構成が現行設計であり、以前の 7 ノード構成は旧版。

> **モード切替**: `mode: "realtime"`（応答 1 件・`cross_run_samples` 不使用・③は上記 pass-through）と `mode: "batch"`（複数応答・③有効）を `config/config.yaml` で切替。①は決定的検証で LLM コスト小、②はルールベース主体に寄せ LLM 呼び出しを最小化。

### Data Flow

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry, max 3)
                                          pre_process

  main 内部（GraphNode → inner DomainWorkflowGraph）:
    response_parse → context_align → citation_consistency_check（①）
      → instruction_drift_check（②）→ cross_run_consistency_score（③）→ qa_report_format
```

### State Definition（flat TypedDict, `AgentState` 継承）

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `response_text` | `str` | 監査対象 RAG エージェントの応答 | ✅ |
| `user_query` | `str` | 元クエリ | ✅ |
| `system_prompt` | `str` | 監査対象の system prompt | ✅ |
| `constraints` | `list[dict]` | 制約セット（disclaimer 必須・禁止表現・口調等） | optional |
| `retrieved_context` | `list[dict]` | RAG ソースチャンク（①②検証用）。dict スキーマ: `{chunk_id: str, text: str, source_url: str, score: float}`（`ContextAlignNode` / `CitationConsistencyCheckNode` がこのキーに依存） | ✅ |
| `cross_run_samples` | `list[str]` | 同一クエリの他応答（③用）。**上限: 最大 20 件・1 件あたり最大 8,000 chars**（`config/config.yaml` で override 可）。超過は S-2 入力ゲートで reject | batch のみ |
| `mode` | `str` | `"realtime"` / `"batch"` | ✅ |
| `claims` | `list[dict]` | 分解された claim | 中間 |
| `citations` | `list[dict]` | 抽出された引用 | 中間 |
| `claim_to_source_map` | `dict` | claim ⇔ source 対応 | 中間 |
| `citation_findings` | `list[dict]` | ①の検出結果 | 中間 |
| `citation_score` | `float` | ①スコア | 中間 |
| `drift_findings` | `list[dict]` | ②の検出結果 | 中間 |
| `consistency_score` | `float` | ③スコア | 中間 |
| `divergence_details` | `dict` | ③の分散詳細 | 中間 |
| `qa_report` | `dict` | 統合 QA レポート（JSON + markdown summary） | 出力 |

**State Constraints (mandatory):**
- Flat TypedDict only（primitives + JSON-serializable types）
- 監査対象応答に PII が含まれ得るが、State / checkpoint に credential（JWT / API key）は格納しない
- InvocationContext は `config["configurable"]` 経由のみ（State に入れない）
- Pydantic models / dataclass / 任意 Python オブジェクト禁止（msgpack 非互換）
- 本テンプレートは監査対象応答を**永続化しない**（QA レポートのみ返す）
- **入力サイズ上限（F-02 対応）**: `cross_run_samples`（最大 20 件 / 8,000 chars）・`retrieved_context`・`response_text` の上限を `config/config.yaml`（`limits:` セクション）で定義し、`pre_process` の S-2 `_extra_security_gate_input()` で超過を `SecurityViolationError` として reject（コスト・レイテンシの無制限膨張を防止）

## Framework Utilization

### Shared Components Used
- [x] InvocationContext（correlation_id, session_id, caller_trust_level, credential handle）
- [x] ConnectionPolicy（LLM 補助呼び出しの retry/timeout）
- [x] SecurityViolationError
- [x] S-2: `_extra_security_gate_input()` — 監査対象 `response_text` / `retrieved_context` に対する PII / 入力サイズの domain check（`pre_process` の `FunctionNode` で実装。framework デフォルト PII scan の後段。`_security_gate_input()` は override しない）
- [x] S-3: `_extra_security_gate_output()` — `qa_report` への credential 混入再チェック（`post_process` の `FunctionNode` で実装。framework デフォルト credential scan の後段。`_security_gate_output()` は override しない）
- [x] S-4: `emit_trace_event()` — LLM 補助（②）・QA レポート生成など side-effect 操作ごとに 1 件以上の domain event を `execute()` 内で emit（`node_start` / `node_complete` / `node_error` は `__call__()` が自動 emit するため重複させない）

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - inner workflow の 6 ノードは `FunctionNode` subclass → framework `@final` ゲートが常時自動実行。domain check は `_extra_security_gate_*()` で拡張のみ。
> - `main` スロットの `QAAuditGraphNode` は `GraphNode` → S-2/S-3 は意図的 no-op（入力ゲートは上流 `pre_process`、出力は子ノード群が適用済み）。
> - `pre_process` / `post_process` は `FunctionNode` subclass → `_extra_security_gate_*()` で domain check。

### Composition Pattern

- **Pattern**: GraphNode（subgraph）— Cat 2 の inner workflow を `main` スロットでラップ
- **Composition target**: `src/graph/domain_workflow_graph.py` の `DomainWorkflowGraph`（inner, `BaseGraph` 継承, linear 6-node topology）
- **Error propagation strategy**: `propagate`（inner graph の例外は `SubgraphError` として再送出し fail-fast）
- **`SubgraphError` の出所（F-05 対応）**: framework 提供（`GraphNode` の `error_strategy="propagate"` が送出）を前提とする。framework が当該例外型を export していない場合は実装フェーズで `src/errors.py` に定義し、`merge_output()` 周辺で wrap する（実装 MR-B で framework の実体を確認して確定）

- **Entry points**: `src/api/server.py`（HTTP `/invoke`）と `cli.py`（AGENTIC STAR Marketplace）の 2 本。
  どちらも adapter でありビジネスロジックを持たない。`cli.py` は `Graph` を継承した `MarketplaceGraph` で
  Marketplace 境界のみを固める（`input_context` の組み直し / `hitl_allowed=False` / 非成功時の
  `output` 補填 / secrets の deny-all 差し替え）。LLM は注入しない（`generation_mode: deterministic`）。
  詳細は `docs/07_operation_guide.md` §8。

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | 固定多段パイプライン（自律ループ不要）。Cat 2 は固定 5 ノード backbone + inner GraphNode |
| Composition pattern | Standalone（単一 main） | GraphNode（inner subgraph） | **GraphNode** | QA 監査は 6 ステップの多段ワークフロー。ドメイン複雑性を inner graph に閉じ Single-responsibility を保つ |
| ④ 事実性検証の扱い | スコープに含める | スコープ外 | **スコープ外** | LLM-as-judge の self-reference 問題で世界知識の真偽を原理的に保証できないため |
| ① の検証方式 | LLM-as-judge | 決定的突き合わせ | **決定的突き合わせ** | 引用 ⇔ retrieved_context の照合は決定的に可能。LLM コスト不要・再現性が高い |
| ② の検証方式 | LLM 主体 | ルールベース主体 + LLM 補助 | **ルールベース主体** | disclaimer 欠落・禁止表現はルールで検出可。LLM は低 confidence 時の補助に限定しコストを抑制 |
