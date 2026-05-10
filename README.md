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
```

批量求解：

```bash
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl
```


## Intern-S1 客户端说明

- 统一通过 `src/math_agent/clients/interns1_client.py` 发起真实模型调用；
- 默认推荐 mock 模式，测试中不会触发任何网络请求；
- 真实模式需要配置 `INTERNS1_API_KEY` 与 `INTERNS1_BASE_URL`。

## Mock 模式

- 默认 `--mock` 为 true；
- 不依赖外部闭源服务；
- 不会读取并使用真实 API key 发起请求。

## JSON 输出格式

每次输出都符合 `MathResult`：

```json
{
  "question_id": "q1",
  "question": "1+1=?",
  "answer": "2",
  "explanation": "Compute 1+1.",
  "success": true,
  "error": null,
  "metadata": {
    "mode": "mock",
    "model": "intern-s1"
  }
}
```

失败时也输出合法 JSON（`success=false`，`error` 非空）。

## Prompt 配置

- 所有 agent prompt 统一维护在 `configs/prompts.yaml`；
- 可通过 `math_agent.prompting` 中的 `load_prompts`、`get_prompt`、`render_prompt` 加载和渲染；
- 配置加载和变量渲染失败时会抛出明确异常，避免静默返回空 prompt。

## Trace 日志与复盘

为满足比赛提交、调试与 Demo 展示需求，pipeline 会为**每道题**生成可复盘 trace JSON（默认开启）。

### 作用

- 每道题会保存一个可复盘 JSON；
- 可用于比赛日志提交、Debug、Demo 展示；
- 单题失败时也会尽量保存 trace（除非显式关闭 trace）；
- trace 会做敏感信息清洗，不应包含 API key、`.env` 内容或其他敏感密钥。

### 默认行为

- `solve` 默认生成 trace；
- `batch` 默认每题生成一个 trace；
- 默认目录：`outputs/traces/`；
- 可用 `--no-trace` 关闭；
- 可用 `--trace-dir` 指定目录。

### 命令示例

单题默认 trace：

```bash
python -m math_agent.cli solve --question "1+1=?" --question-id q1
```

单题自定义 trace 目录：

```bash
python -m math_agent.cli solve --question "1+1=?" --question-id q1 --trace-dir outputs/traces
```

单题关闭 trace：

```bash
python -m math_agent.cli solve --question "1+1=?" --question-id q1 --no-trace
```

批量默认 trace：

```bash
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl
```

批量关闭 trace：

```bash
python -m math_agent.cli batch --input data/sample_questions.jsonl --output outputs/results.jsonl --no-trace
```

### Trace JSON 字段示例

```json
{
  "question_id": "q1",
  "question": "1+1=?",
  "started_at": "...",
  "finished_at": "...",
  "latency_seconds": 0.01,
  "prompt_version": "default",
  "route_info": {},
  "model_calls": [],
  "tool_calls": [],
  "verifier_result": {},
  "final_result": {},
  "errors": []
}
```

字段说明（简要）：

- `route_info`：路由器给出的领域/题型判断；
- `model_calls`：各阶段模型调用摘要（默认只保留摘要，减少日志体积并降低隐私风险）；
- `tool_calls`：工具调用轨迹；
- `verifier_result`：校验器输出；
- `final_result`：最终 `SolveResult`；
- `errors`：执行过程中捕获的错误列表。

### 产物与提交建议

- `outputs/traces/` 是运行产物，不建议提交到 Git；
- 比赛提交时可将 `traces/` 与结果 JSON 一起打包；
- 生产或公开场景建议定期抽检 trace 脱敏效果。
