# Intern-S1 Math Agent

基于 Intern-S1 API 的数学智能体系统（初赛工程验收版）。

## 1) 项目状态

- **当前状态**：初赛工程版已完成，**Ready for official dataset**。
- **官方 112 题集**：截至 2026-05-14 尚未公布，正式结果需在题集发布后生成。
- **预官方 18 领域覆盖测试（非官方成绩）**：
  - total = 18
  - json_valid_rate = 100%
  - success = 18
  - partial = 0
  - fail = 0
  - trace_count = 18
  - zero_model_calls = 0
  - dirty_boxed = 0
  - missing_final = 0

> 说明：以上 18 题为自构造覆盖验收，不代表官方 112 题正式榜单成绩。

## 2) 赛题背景

本项目面向 Intern-S1 数学智能体竞赛，目标是在**不训练底座模型**前提下，围绕智能体推理流程实现：

- 题目理解与结构化解析
- 解题规划
- 模型调用与工具增强
- 过程校验
- 教学化解释
- 严格 JSON 输出

初赛聚焦单智能体解题、解释与结构化输出；决赛可在此基础上扩展为多智能体协作与更丰富的 Web/Notebook 展示。

## 3) 当前能力

当前仓库已具备以下能力（与现有工程实现一致）：

- 自然语言数学题输入
- Router 题型识别
- Planner 解题规划
- Solver 调用 Intern-S1
- Python / SymPy 工具增强
- Verifier 校验
- final_answer 格式化
- proof 题特殊格式处理
- `solve` 单题求解
- `batch` JSONL 批量运行
- trace 日志记录与复盘
- 评测报告生成（`scripts/evaluate_results.py`）
- Streamlit Demo
- submission 导出脚本（`scripts/export_submission.py`）

## 4) 系统架构

```text
Input Question
  -> Router
  -> Planner
  -> Solver / Intern-S1
  -> Tools: Python / SymPy
  -> Verifier
  -> Formatter
  -> SolveResult JSON
  -> Trace / Evaluation
```

## 5) 运行模式

### API 调用模式

- **mock（默认）**：不调用真实 API。
- **real（显式 `--real`）**：调用真实 Intern-S1 API。

### 推理策略模式（`--mode`）

- **full（默认）**：完整链路，适合最终提交。
- **fast**：调试优先，减少模型调用。
- **tool-first**：计算题/方程题优先工具求解，必要时再回退模型。

> 不传 `--mode` 等价于 `--mode full`。

## 6) 安装方式

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## 7) 环境变量与安全

```bash
cp .env.example .env
```

在 `.env` 中配置：

- `INTERNS1_API_KEY`
- `INTERNS1_BASE_URL`
- `INTERNS1_MODEL`

安全要求：

- `.env` 不得提交。
- 不得提交 API key。
- trace 中不应出现 API key / Authorization / Bearer 明文。

## 8) CLI 使用

### Mock 单题

```bash
python -m math_agent.cli solve --question "计算 2+3" --enable-tools
```

### Real 单题

```bash
python -m math_agent.cli solve \
  --question "计算 1+1" \
  --question-id smoke_001 \
  --real \
  --enable-tools \
  --trace-dir outputs/traces_real
```

### Mock batch

```bash
python -m math_agent.cli batch \
  --input data/sample_questions.jsonl \
  --output outputs/mock_results.jsonl \
  --enable-tools
```

### Real batch

```bash
python -m math_agent.cli batch \
  --input data/smoke_questions.jsonl \
  --output outputs/real_smoke_results.jsonl \
  --real \
  --enable-tools \
  --trace-dir outputs/traces_real
```

### Fast mode

```bash
python -m math_agent.cli batch \
  --input data/sample_questions.jsonl \
  --output outputs/results_fast.jsonl \
  --real \
  --enable-tools \
  --mode fast
```

### Tool-first

```bash
python -m math_agent.cli solve \
  --question "解方程 2x+5=13" \
  --real \
  --enable-tools \
  --mode tool-first
```

## 9) JSON 输出格式

- `solve` 输出单个 `SolveResult` JSON。
- `batch` 输出 JSONL（每行一个 `SolveResult`）。
- 典型字段包括：
  - `question_id`
  - `domain`
  - `problem_type`
  - `problem_parse`
  - `solution_plan`
  - `visible_solution_steps`
  - `tool_trace`
  - `final_answer`
  - `verification`
  - `didactic_hint`
  - `confidence`
  - `status`
  - `error`

状态约定：

- `success`：成功求解并通过主要检查。
- `partial`：部分完成或存在不确定项。
- `fail`：失败，但仍必须输出合法 JSON（包含 `error`）。

## 10) Trace 日志

- 默认生成 trace。
- `--trace-dir` 指定目录。
- `--no-trace` 关闭 trace。
- trace 关键内容：`model_calls`、`tool_calls`、`verifier_result`、`final_result`、`errors`。
- trace 属于运行产物，默认不建议提交 Git。
- 提交材料时可与 results 一并打包。

## 11) 评测

```bash
python scripts/evaluate_results.py \
  --results outputs/real_smoke_results.jsonl \
  --report outputs/real_smoke_evaluation_report.md
```

评测指标包括：

- `total`
- `json_valid_count`
- `json_valid_rate`
- `success_count`
- `partial_count`
- `fail_count`
- `verifier_pass_rate`
- `average_confidence`
- `domain_distribution`
- `problem_type_distribution`

## 12) 预官方 18 领域验收结果（非官方）

该结果来自自构造覆盖测试，目的为工程验收，不是官方榜单：

- 18 题
- `json_valid_rate = 100%`
- `success = 18`
- `partial = 0`
- `fail = 0`
- `trace_count = 18`
- `zero_model_calls = 0`
- `dirty_boxed = 0`
- `missing_final = 0`

## 13) 官方题集运行流程（112 题发布后）

官方题集发布后建议流程：

1. 转换为 `data/official_questions.jsonl`
2. 运行 official batch
3. 生成 `outputs/official_results.jsonl`
4. 生成 `outputs/official_evaluation_report.md`
5. 保存 `outputs/traces_official_112`

示例命令：

```bash
python scripts/convert_dataset.py \
  --input <官方题集文件> \
  --output data/official_questions.jsonl

time python -m math_agent.cli batch \
  --input data/official_questions.jsonl \
  --output outputs/official_results.jsonl \
  --real \
  --enable-tools \
  --trace-dir outputs/traces_official_112

python scripts/evaluate_results.py \
  --results outputs/official_results.jsonl \
  --report outputs/official_evaluation_report.md
```

## 14) Streamlit Demo

```bash
streamlit run demo/streamlit_app.py
```

Demo 可展示：

- 题型识别
- 解题计划
- 可见推理步骤
- 工具调用
- 校验结果
- 最终 JSON
- trace 路径

## 15) 项目结构

```text
configs/
data/
demo/
scripts/
src/math_agent/
tests/
outputs/   # 运行产物，不提交
```

## 16) 当前限制

- 官方 112 题集尚未公布，尚未生成 `official_results.jsonl`。
- 高难 proof 题效果仍依赖模型推理质量。
- `full` 模式耗时较高（单题可能多次模型调用）。
- `fast` / `tool-first` 适合调试；最终提交建议优先 `full`。

## 17) 提交材料建议

- `results.jsonl`
- `traces/`
- `evaluation_report.md`
- 技术方案 PDF
- 展示视频
- 源码或 Notebook
- `README_SUBMISSION.md`

## 18) 安全与合规

- 不提交 `.env`
- 不提交 API key
- 不伪造日志
- 不人工逐题改答案
- `outputs/` 作为运行产物默认不进 Git

---

如需快速开始，建议先运行 mock 单题与 mock batch 验证流程，再在已配置 `.env` 的前提下通过 `--real` 做小规模 smoke，最后等待官方 112 题集发布后执行正式批量评测。
