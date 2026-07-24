# 挑战杯初赛提交说明

## 题目

基于 Intern-S 系列模型的数学智能体设计与推理创新

## 提交入口

本仓库根目录提供官方初赛 baseline 约定入口：

```text
user_agent.py
```

评测平台可按如下方式加载：

```python
from user_agent import ReasoningAgent

agent = ReasoningAgent(client=official_client)
result = agent.solve(problem, metadata)
```

`solve` 返回 JSON 可序列化字典，核心字段包括：

- `final_response`: 非空最终答案字符串。
- `trace`: 关键路由、求解、工具与校验摘要。
- `success`: 本地 schema 层面的成功标记。
- `status`: 当前 pipeline 状态。
- `error`: 失败时补全的错误类型和信息。

## 运行依赖

正式评测或本地复现前安装：

```bash
pip install -r requirements.txt
```

依赖文件不包含 API key；正式评测使用平台提供的 official client。

## 本版策略

- 默认复用冻结的 stable pipeline，不改既有 CLI 行为。
- `ReasoningAgent` 只作为官方 baseline 入口适配层。
- 官方 client 统一经 `user_agent.py` 注入现有 `MathAgentPipeline`。
- 入口默认 `run_mode="fast"`、`enable_tools=True`、`save_trace=False`，减少模型调用和磁盘产物。
- 不读取标准答案，不依赖隐藏数据，不写入 `outputs/` 或 trace 文件。

## 提交前待填写

- 队伍名称：
- 仓库地址：
- 分支名称：
- commit hash：
- 选择使用的模型：例如 `intern-s2-preview`
- 代码 zip 文件名：

## 提交前检查

- `user_agent.py` 可正常 import。
- `ReasoningAgent(client=official_client)` 可初始化。
- `solve(problem, metadata)` 返回非空 `final_response`。
- `requirements.txt` 已包含运行依赖。
- 仓库中无 `.env`、API key、`outputs/`、`trace/`、`official_results.jsonl`、`submission.zip`。
