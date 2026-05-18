# EvoExternMath-S1++ Codex 开发规范

## 0) 背景与范围
- 当前仓库已完成 Step 0 只读审计，并已具备 stable pipeline。
- 本规范用于后续 Codex 协作开发与提交流程约束。
- 默认运行模式保持 **mock**；不得默认真实调用外部 API。

## 1) Stable Pipeline 不动
- Stable Pipeline 视为冻结基线，不做重构、不改流程编排。
- 不修改既有 CLI 行为（参数、默认值、输出契约保持兼容）。
- 如需增强，必须以可插拔方式实现，不破坏主路径。

## 2) PR 与任务管理
- 严格执行 **一个任务一个 PR**。
- 每个 PR 必须可独立审阅、独立回滚、独立验证。
- 避免在单个 PR 中混入无关改动。

## 3) 测试门禁
- **每个 PR 必须运行 `pytest -q` 并通过**。
- 测试不得真实调用 API。
- 新增能力至少包含最小可复现测试或断言。

## 4) 安全与产物提交边界
- 严禁提交：`.env`、任何 API key/secret。
- 严禁提交：`outputs/`、`trace/`、`official_results.jsonl`。
- 不得在代码、测试、README、日志中泄露密钥信息。

## 5) 结果文件与审计纪律
- **禁止人工修改 `official_results.jsonl`**。
- 禁止伪造 trace、日志或评测记录。
- 禁止赛后补填或篡改结果。

## 6) 增强策略与优先级
- 所有增强必须具备明确回退方案（开关、配置或可逆补丁）。
- **Voting 默认关闭**；未经评审不得默认开启。
- **MemoryHub 默认不写入**；仅在明确批准后开启写入。
- **MultiAgent 暂时不做**，避免引入额外不确定性。
- 研发优先级：**Formatter Repair / Proof Guardian 高于花活增强**。

## 7) 模型与提示词约束
- 所有模型调用统一走 `src/math_agent/clients/interns1_client.py`。
- 所有 prompt 统一维护在 `configs/prompts.yaml`。
- 输出必须经过 schema 校验，失败时返回 `success=false` 且补全 `error` 字段。

## 8) 任务完成时的标准汇报
每次任务结束必须明确给出：
1. 修改文件清单；
2. 测试结果（含 `pytest -q`）；
3. 风险点；
4. 回退方式。
