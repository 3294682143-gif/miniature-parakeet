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
