# interns1-math-agent Agent Notes

## 1) 项目目标
基于 Intern-S1 API 实现数学智能体，支持以下能力：
- 题目理解
- 解题规划
- 工具增强（允许本地 Python / SymPy，可审计）
- 过程校验
- 教学解释
- JSON 输出
- 批量评测
- Demo 展示

## 2) 比赛约束
- 不训练底座模型。
- 核心模型调用 Intern-S1 API。
- 不允许人工逐题干预。
- 不允许伪造日志。
- 不允许赛后补填结果。
- 不允许使用未经允许的外部闭源服务代答。
- 允许本地 Python / SymPy 作为可审计工具。
- 所有输出必须是合法 JSON。
- 单题失败不能导致批量任务中断。

## 3) 工程原则
- Default runtime mode is **mock**. Do not call any external API by default.
- 每个功能必须有最小测试。
- 测试不能真实调用 API。
- Never hardcode or commit secrets/API keys。
- API key 不能出现在代码、测试、README、日志中。
- 所有模型调用必须经过 `src/math_agent/clients/interns1_client.py`。
- 所有 prompt 统一放 `configs/prompts.yaml`。
- 所有输出必须经过 Pydantic schema 校验（包含 `MathResult`）。
- 每道题必须保存 trace。
- mock 模式必须全流程可用。
- On failures, return schema-compliant JSON with `success=false` and populated `error`.

## 4) 每次完成任务后的回复格式
每次完成任务后，回复中必须包含：
- 修改了哪些文件
- 如何运行
- 测试结果
- 未完成事项
- 风险提示
