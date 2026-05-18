# Baseline Freeze（Stable Pipeline）

## 当前状态

- **Ready for official dataset**。

## 当前 stable pipeline 能力

- API 调用模式：`mock` / `real`
- 运行方式：`solve` / `batch`
- 推理策略：`full` / `fast` / `tool-first`
- 结果产物：JSONL 输出
- 过程产物：trace 日志
- 工具能力：SymPy / Python 工具

## 当前质量门槛

- `json_valid_rate = 1.0`
- `missing_final = 0`
- `dirty_boxed = 0`
- `contains_42_fallback = 0`
- `trace_count = question_count`
- `zero_model_calls = []`

## 当前禁止事项

- 不人工修改 `official_results.jsonl`
- 不伪造 trace / 日志
- 不提交 `.env`
- 不提交 API key
- 不提交 `outputs/` / `trace/` / `run_records/`
- 不提交官方私有题集

## 回退要求

- 后续增强必须具备可逆性，并可回退到 **Stable Pipeline Mode**。
