# interns1-math-agent

基于 Intern-S1 风格接口的数学智能体项目脚手架（当前仅 **mock 模式**），用于自动解题并输出严格 JSON 结果。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

开发依赖：

```bash
pip install -e .[dev]
```

## 环境变量

复制示例文件：

```bash
cp .env.example .env
```

本项目默认不会真实调用 API（mock-only）。

## CLI 用法

单题求解：

```bash
python -m math_agent.cli solve --question "1+1=?"
python -m math_agent.cli solve --question "计算 2+3" --enable-tools
```

批量求解：

```bash
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl --enable-tools
```



## 官方题集转换

- 原始题集（raw 数据）不要提交到仓库。
- 转换后的 `data/official_questions.jsonl` 可直接用于 batch 求解。

```bash
python scripts/convert_dataset.py --input data/raw_questions.jsonl --output data/official_questions.jsonl
python -m math_agent.cli batch --input data/official_questions.jsonl --output outputs/results.jsonl --mock --enable-tools
```

## Streamlit Demo

运行比赛展示 Demo：

```bash
streamlit run demo/streamlit_app.py
```

说明：
- 默认 `mock` 开启，不会真实调用 Intern-S1 API；
- 只有在手动关闭 `mock` 且本地配置好环境变量时，才会尝试真实调用；
- Demo 会展示路由、规划、工具调用、校验、最终 JSON 与 trace 路径。

## Intern-S1 客户端说明

- 统一通过 `src/math_agent/clients/interns1_client.py` 发起真实模型调用；
- 默认推荐 mock 模式，测试中不会触发任何网络请求；
- 真实模式需要配置 `INTERNS1_API_KEY` 与 `INTERNS1_BASE_URL`。

## Mock 模式

- 默认 `--mock` 为 true；
- 不依赖外部闭源服务；
- 不会读取并使用真实 API key 发起请求。

## JSON 输出格式

`solve` 命令输出 **一个** `SolveResult` JSON；`batch` 命令输出 **JSONL**，其中每一行都是一个 `SolveResult` JSON。

示例（`SolveResult`）：

```json
{
  "question_id": "sample_001",
  "domain": "Calculus",
  "problem_type": "calculation",
  "problem_parse": {
    "goal": "计算 2+3",
    "givens": [],
    "symbols": []
  },
  "solution_plan": ["识别为基础计算题并执行运算"],
  "visible_solution_steps": ["2+3=5"],
  "tool_trace": [
    {
      "tool": "sympy",
      "purpose": "simple arithmetic",
      "status": "success",
      "summary": "2+3 -> 5"
    }
  ],
  "final_answer": {
    "type": "number",
    "value": "5",
    "boxed": "\\boxed{5}"
  },
  "verification": {
    "method": "numeric_check",
    "passed": true,
    "notes": "tool-based numeric check passed"
  },
  "didactic_hint": "先识别运算类型，再逐步计算。",
  "confidence": 0.85,
  "status": "success",
  "error": null
}
```

说明：
- `status` 可能为 `success` / `partial` / `fail`；
- 单题失败时依然返回合法 `SolveResult` JSON（`status="fail"` 且 `error` 非空）；
- 批量模式中某一题失败不会中断任务，仍会继续处理后续题目并逐行输出合法 JSON。

## Prompt 配置

- 所有 agent prompt 统一维护在 `configs/prompts.yaml`；
- 可通过 `math_agent.prompting` 中的 `load_prompts`、`get_prompt`、`render_prompt` 加载和渲染；
- 配置加载和变量渲染失败时会抛出明确异常，避免静默返回空 prompt。

## Trace 日志与复盘

- trace 用于比赛日志提交、Debug、Demo 展示；
- `solve` / `batch` 默认生成 trace；
- 默认目录 `outputs/traces/`；
- `--no-trace` 可关闭；
- `--trace-dir` 可指定目录；
- `outputs/traces/` 是运行产物，不建议提交 Git；
- 比赛提交时可以把 `traces/` 随 `results.jsonl` 一起打包；
- trace 中 `model_calls` 默认只保存摘要，避免日志过大和隐私风险；
- trace 不应包含 API key、`.env` 内容或敏感密钥。

示例：

```bash
python -m math_agent.cli solve --question "1+1=?" --question-id q1
python -m math_agent.cli solve --question "1+1=?" --question-id q1 --trace-dir outputs/traces
python -m math_agent.cli solve --question "1+1=?" --question-id q1 --no-trace
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl --no-trace
```
