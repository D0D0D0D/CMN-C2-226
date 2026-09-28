# Test Specification — CMN-C2-226

> Agent Output Hallucination & Quality Anomaly Detection Agent
> スコープ: ① citation consistency ② instruction drift ③ cross-run consistency。
> ④ world-knowledge factuality はスコープ外。

## テスト構成

| 種別 | パス | 内容 |
|---|---|---|
| Unit | `tests/unit/test_nodes.py` | 各ノード・サービスの単体検証（41 ケース中の大半） |
| Integration | `tests/integration/test_invoke.py` | `Graph().invoke()` のフロー検証（success / realtime / oversize / empty 等） |
| Proof-of-Boundary | `tests/proof_of_boundary/` | State 安全性（PB-2/5）・Import 分離（PB-4） |

実行: `python -m pytest tests/ -v` / `python -m pytest tests/proof_of_boundary/ -v`（Python 3.11 + `agenticstar-agentcore==1.0.0`）。

## Test Cases（TC）

| TC-ID | 対象 | シナリオ | 期待結果 |
|---|---|---|---|
| TC-01 | State 契約 | `src/schemas/state.py` を AST スキャン | credential フィールド・Pydantic/InvocationContext 型なし（PB-2） |
| TC-02 | pre_process | 不正 JSON / 空入力 / response_text 欠落 | `status=ERROR` + error_log |
| TC-03 | Credential | `gate-credential-scan` CI | `src/` に sk-/JWT/AKIA パターンなし |
| TC-04 | S-2 size gate | `cross_run_samples` 25 件 | `SecurityViolationError`（DoS/コスト guard, F-02） |
| TC-05 | S-4 audit | ①②・post_process | `emit_trace_event` を `execute()` 内で発火（citation/drift/qa_report_generated） |
| TC-06 | ① citation | cited chunk が claim を裏付けない | `unsupported_citation`（high） |
| TC-07 | ① citation | 存在しない chunk を引用 | `missing_source`（high） |
| TC-08 | ② drift | disclaimer 必須なのに欠落 | `disclaimer_required` finding |
| TC-09 | ② drift | forbidden_phrase 含有 | `forbidden_phrase` finding |
| TC-10 | ② drift | 制約遵守の応答 | findings 空 |
| TC-11 | ③ consistency | `mode=realtime` | pass-through（score=1.0, details.mode=realtime, F-03） |
| TC-12 | ③ consistency | batch 複数 sample | 0.0–1.0 のスコア + n_samples |
| TC-13 | report | high finding あり | `overall=fail`、summary 集計一致 |
| TC-14 | invoke | フル success 経路 | `status=SUCCESS`、qa_report に scope/out_of_scope、node 5 件順序 |
| TC-15 | node 契約 | 全ノード | `execute(self, state)` 実装・`_invoke_impl` 不在（ノード契約） |

## Proof-of-Boundary（PB）

| PB-ID | 境界 | 検証 |
|---|---|---|
| PB-2/5 | State serialization | flat TypedDict・credential/Pydantic なし（`test_state_safety.py`） |
| PB-4 | Import isolation | `src/` が Level 0（agenticstar）を import しない（`test_import_isolation.py`） |
| PB-6 | Invoke 実行順 | backbone 5 ノード順序 = Initialize→PreProcess→QAAuditGraphNode→PostProcess→Finalize（`test_backbone_node_order`） |

## カバレッジ方針

- 各ノードの正常系・異常系（error short-circuit）・境界（realtime/batch, oversize）を網羅。
- LLM 補助はスコープ外（v1 ルールベース）。`NullLLMClient`（disabled）で決定的。
- ④ world-knowledge factuality はスコープ外のためテスト対象外（self-reference により検証不能）。
