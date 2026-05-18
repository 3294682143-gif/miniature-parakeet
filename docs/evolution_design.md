# EvoExternMath-S1++ Offline Evolution Layer Design (Step 14 Skeleton)

## 1) 定位与边界

Offline Evolution Layer 仅用于**赛前离线优化**，不参与正式评测时的在线策略变更。

核心原则：
- 仅离线使用：用于准备候选改动与回归验证。
- 正式提交使用 **Frozen Harness**（冻结流程 + 冻结候选）。
- 禁止 online self-modification（禁止在线自改）。
- 禁止在正式评测中动态改代码或改提示词。
- 禁止人工逐题修改 `official_results.jsonl`。
- 禁止伪造 trace / 日志 / 评测记录。

## 2) 允许演化的组件范围

允许在离线阶段通过可审计清单演化以下组件：
- `configs/prompts.yaml`
- `configs/budgets.yaml`
- `skills/*.skill.md`
- `memory/error_taxonomy.json`
- `src/math_agent/formatter_repair.py`
- `src/math_agent/proof_guardian.py`
- `src/math_agent/verifier.py`
- `src/math_agent/weighted_voting.py`
- `src/math_agent/budget_scheduler.py`
- replay / demo 展示层

说明：以上变更须通过 change manifest、证据报告与回归门禁后，才能成为可提升候选。

## 3) 禁止修改范围

以下对象禁止在 Offline Evolution 中被“优化”或绕过：
- `official_results.jsonl`
- official traces
- API key handling
- submission exporter 的安全过滤
- evaluation 脚本统计口径绕过逻辑
- `.env` / secret 相关文件

## 4) Candidate Promotion 条件

候选版本进入 promoted 状态前，至少满足：
- `pytest -q` 通过；
- JSON 合法率不下降；
- `missing_final = 0`；
- `dirty_boxed = 0`；
- `trace_count = question_count`；
- `regression_failures = 0`；
- 不泄露 API key；
- 存在明确可执行回退方案。

## 5) 标准流程（离线）

Run stable harness
→ Collect traces
→ Analyze failures
→ Write evidence report
→ Create change manifest
→ Apply candidate patch
→ Run unit tests
→ Run shadow eval
→ Run regression eval
→ Compare candidates
→ Promote or rollback
→ Freeze final harness

## 6) 与现有模块关系

- **Trace Replay**：提供可回放证据用于 failure analysis。
- **MemoryHub**：保存 error taxonomy / regression memory（默认不写入，需显式批准）。
- **Skill Library**：作为可审计技能资产库，支撑可追踪改动。
- **Budget Scheduler**：用于候选实验预算控制（离线使用，不接主流程）。
- **Weighted Voting**：候选选择机制之一（离线评估，不接主流程）。
- **Frozen Submission exporter**：用于最终安全打包与冻结提交。

## 7) 审计与回退

每次离线候选变更必须绑定：
- 证据（evidence report）；
- 变更清单（change manifest）；
- 验证计划与门禁结果；
- 回退说明（可立即恢复到稳定基线）。

这保证了 stable pipeline 不被破坏，且每次增强都可独立审阅、验证与回滚。
