# MemoryHub v1 Assets

Memory 是外化状态存储，不是聊天记忆。

## 约束
- 默认不在 `solve` / `batch` 中自动写入。
- 所有写入必须由显式接口调用。
- 禁止写入 API key、`Authorization`、`Bearer`、`.env` 内容。
- 禁止写入官方私有题集原文。
- 正式提交流程以 Frozen Harness 为准。

## 资产说明
- `error_taxonomy.json`: 常见失败分类定义。
- `regression_cases.yaml`: 回归样例结构（仅示例）。
- `route_stats.json`: 路由统计聚合。
- `skill_success_stats.json`: skill 成功率统计。
- `verifier_failures.json`: verifier 失败样例（脱敏后）。
- `answer_cluster_stats.json`: 答案聚类统计。
