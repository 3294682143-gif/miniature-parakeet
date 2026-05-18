# Trace Replay Guide

## 1) Trace Replay 的用途
- 将单题或批量运行的 trace 还原为可读时间线。
- 用于故障定位、策略复盘、答辩展示与 Demo 讲解。
- 作为 Offline Evolution 的证据输入之一。

## 2) 基本用法

```bash
python scripts/replay_trace.py --trace <trace.json>
python scripts/replay_trace.py --trace-dir <trace_dir> --out docs/replay_summary.md
```

说明：
- `--trace`：重放单个 trace 文件。
- `--trace-dir`：批量读取目录中的 trace。
- `--out`：输出汇总 markdown 报告。

## 3) timeline 字段说明
- `timeline` 记录关键事件序列（如路由、规划、模型调用、工具调用、校验、格式化）。
- 每个事件建议包含时间戳、事件类型、摘要、状态。
- timeline 用于回答“系统在什么时候做了什么，为什么失败/成功”。

## 4) summary 字段说明
- `summary` 提炼关键统计与结论。
- 常见包括：模型调用次数、工具调用次数、最终状态、异常摘要。
- summary 用于横向比较不同运行配置或策略版本。

## 5) 脱敏说明
- Trace 中不得包含 API key、Authorization、Bearer 等敏感信息。
- 共享演示材料前需执行脱敏检查。
- `.env` 与任何密钥文件不得进入提交包。

## 6) Demo 如何展示 replay
- 在 Streamlit Demo 中选择单题 trace 展示完整 timeline。
- 对比两次运行 summary，讲解策略变化带来的影响。
- 用失败案例回放演示 verifier / formatter 的保护作用。
- 明确区分：replay 是工程复盘证据，不是官方成绩证明。
