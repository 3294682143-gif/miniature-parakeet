# Current Baseline Audit (Read-only)

> 审计时间：2026-05-18（UTC）
> 范围：当前仓库 stable pipeline 的关键文件、CLI 参数、测试、trace、评测、Demo、提交脚本。

## 1) 当前项目结构概览

顶层关键目录（按功能）：

- `src/math_agent/`：核心业务代码（CLI、pipeline、agents、schema、工具、日志）。
- `configs/`：默认配置与 prompts。
- `tests/`：单元/集成测试。
- `scripts/`：数据转换、评测、批处理与提交相关脚本。
- `demo/`：Streamlit Demo 入口。
- `data/`：示例题数据。
- `outputs/`：运行产物（trace/results/report）。

仓库现状可见：包含 `outputs/traces/` 目录，说明本地运行产物路径已预置。是否提交由 `.gitignore` 控制（见风险章节）。

## 2) CLI 支持的命令和参数

核心入口：`python -m math_agent.cli`。

### `solve`

参数：

- `--question`（必填）
- `--question-id`（默认 `cli_q`）
- `--real`（默认 false；开启真实 API）
- `--enable-tools`（默认 false）
- `--trace-dir`（默认 `outputs/traces`）
- `--no-trace`（默认 false；开启后不写 trace）
- `--mode`（可选：`full` / `fast` / `tool-first`，默认 `full`）

行为：
- `--real` 开启时，会先执行真实配置校验（缺 `INTERNS1_API_KEY` 或 `INTERNS1_BASE_URL` 会报错）。
- 输出单个 `SolveResult` JSON 到 stdout。

### `batch`

参数：

- `--input`（必填，JSONL）
- `--output`（必填，JSONL）
- `--real`
- `--enable-tools`
- `--trace-dir`
- `--no-trace`
- `--mode`

行为：
- 逐行读取输入 JSONL，逐题生成结果。
- 单题异常不会中断批处理；会回退到 `make_failure_result(...)` 并继续。
- 输出每行一个 `SolveResult` JSON。

## 3) 当前 JSON schema 结构

核心模型定义位于 `src/math_agent/schemas.py`：

- `MathQuestion`
  - `question: str`
  - `question_id: str = "unknown"`

- `SolveResult`（兼容别名：`MathResult = SolveResult`）
  - `question_id: str`
  - `domain: str`
  - `problem_type: str`
  - `problem_parse: ProblemParse`
    - `goal: str`
    - `givens: list[str]`
    - `symbols: list[str]`
  - `solution_plan: list[str]`
  - `visible_solution_steps: list[str]`
  - `tool_trace: list[ToolTrace]`
    - `tool: Literal["python", "sympy", "none"]`
    - `purpose: str`
    - `status: Literal["success", "fail", "skipped"]`
    - `summary: str`
  - `final_answer: FinalAnswer`
    - `type: Literal["number", "expression", "set", "proof", "algorithm", "text"]`
    - `value: str`
    - `boxed: str`
  - `verification: Verification`
    - `method: Literal["symbolic_check", "numeric_check", "substitution", "logic_review", "self_review", "none"]`
    - `passed: bool`
    - `notes: str`
  - `didactic_hint: str`
  - `confidence: float`（0~1）
  - `status: Literal["success", "partial", "fail"]`
  - `error: str | None`

失败场景统一通过 `make_failure_result()` 生成 schema-compliant JSON（`status="fail"`, `error` 已填充）。

## 4) 当前 trace 文件结构

trace 由 `src/math_agent/pipeline.py` 组装、`src/math_agent/logging_utils.py` 落盘。

默认路径：`outputs/traces/{question_id}.json`（可通过 `--trace-dir` 覆盖；`--no-trace` 关闭）。

当前 trace payload 字段：

- `question_id`
- `question`
- `started_at`
- `finished_at`
- `latency_seconds`
- `prompt_version`
- `run_mode`
- `route_info`
- `model_calls`（列表）
- `model_calls_count`
- `tool_calls`（列表）
- `verifier_result`
- `final_result`（即最终 `SolveResult`）
- `errors`（列表）

脱敏逻辑：
- `logging_utils.sanitize_trace()` 会基于 key 和字符串模式清理 `api_key / authorization / bearer / token / secret / password / .env` 等敏感信息。

## 5) 当前已有测试列表

`tests/` 当前测试文件：

- `test_agents_basic.py`
- `test_cli.py`
- `test_convert_dataset.py`
- `test_demo_smoke.py`
- `test_interns1_client.py`
- `test_logging_trace.py`
- `test_metrics.py`
- `test_no_eval_usage.py`
- `test_normalizer.py`
- `test_pipeline_mock.py`
- `test_pipeline_proof_formatting.py`
- `test_pipeline_tools.py`
- `test_prompting.py`
- `test_python_sandbox.py`
- `test_real_mode_contract.py`
- `test_router.py`
- `test_run_modes.py`
- `test_schema.py`
- `test_sympy_tools.py`

执行命令：`pytest -q`。

## 6) 当前 README 中的运行方式

README 覆盖了以下运行方式：

- 安装：`pip install -e ".[dev]"`
- 测试：`pytest -q`
- 单题（mock）
- 单题（real）
- 批量（mock）
- 批量（real）
- `--mode fast`
- `--mode tool-first`
- 评测脚本：`python scripts/evaluate_results.py --results ... --report ...`
- 官方 112 题发布后的建议流程
- Demo 启动：`streamlit run demo/streamlit_app.py`

## 7) 当前风险审计

### A. 是否可能提交 outputs

**有可能，风险中等。**

- README 明确建议 `outputs/` 不提交。
- 但 `.gitignore` 里没有 `outputs/` 或 `outputs/**` 规则。
- 当前仓库已有 `outputs/traces/` 目录存在。

结论：靠“约定”而非“机制”防提交，误提交流程产物的风险仍在。

### B. 是否可能泄露 `.env`

**直接提交 `.env` 风险较低，间接泄露风险中低。**

- `.gitignore` 已忽略 `.env`。
- trace 写入前有脱敏逻辑，包含 `authorization/bearer/api_key/.env` 模式。
- 但脱敏是规则匹配，不保证覆盖所有变体（例如极端拼写/编码）。

### C. 是否存在真实 API 测试

**在测试中不直接访问真实外部 API。**

- `test_real_mode_contract.py` 使用 `FakeClient` 注入 pipeline，验证 real 流程契约，不是网络实调用。
- CLI 测试默认未加 `--real`。
- 仓库有 `scripts/smoke_interns1.py`（人工 smoke 脚本），不在 pytest 默认回归链路。

### D. 是否存在 hardcoded fallback

**存在，且是显式设计。**

- mock / fallback 路径中存在固定答案与占位逻辑（例如失败结果模板、某些 mock 返回）。
- 这本身用于“默认 mock 可运行”和“失败不崩批处理”，符合工程目标；但若切 real 评测，需确认 fallback 不会掩盖真实失败原因。

### E. 是否存在 schema 不兼容风险

**存在轻中度风险。**

- `SolveResult` 字段较严格（Literal + 必填结构）。
- pipeline 内部多阶段输出会被整形成 `SolveResult`，正常路径较稳。
- 兼容性风险主要来自未来扩展时：
  - 若新增状态值/answer type/method 未同步 `Literal`；
  - 若上游脚本（评测/提交）假设旧字段不变。

## 8) 后续增强“不要碰哪些文件”建议

为保持 stable baseline 可复现，后续增强建议分层：

### 建议冻结（非必要不改）

1. `src/math_agent/schemas.py`
   - 基线 JSON 合约定义。
2. `src/math_agent/cli.py`
   - 当前命令行契约（参数名与默认值）。
3. `src/math_agent/clients/interns1_client.py`
   - 外部模型调用唯一入口约束。
4. `configs/prompts.yaml`
   - 统一 prompt 管理的单一来源。
5. `tests/test_schema.py`、`tests/test_cli.py`、`tests/test_real_mode_contract.py`
   - 作为回归护栏。

### 可增强区域（优先）

- 新增脚本/新模块（例如 `src/math_agent/extensions/*`）承接实验功能。
- 在不改 schema 的前提下新增可选字段时，先评估评测脚本兼容性。
- 完善 `scripts/export_submission.py`（当前仅 scaffold）。
- 修复/校对 `scripts/batch_solve.py` 与当前 CLI 的一致性（当前文件引用 `from math_agent.cli import app`，与现有 `argparse` 入口不一致）。

---

## 补充：stable pipeline 关键文件清单（快速索引）

- CLI：`src/math_agent/cli.py`
- Pipeline：`src/math_agent/pipeline.py`
- Schema：`src/math_agent/schemas.py`
- Trace：`src/math_agent/logging_utils.py`
- 客户端：`src/math_agent/clients/interns1_client.py`
- Prompt：`configs/prompts.yaml`
- 评测脚本：`scripts/evaluate_results.py`
- 提交脚本：`scripts/export_submission.py`（当前待完善）
- Demo：`demo/streamlit_app.py`

