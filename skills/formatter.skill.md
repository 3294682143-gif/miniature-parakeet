name: formatter
applies_to: output_format, schema_repair, finalization
input_features: 输出字段缺失、脏 boxed、长 markdown 污染、schema 风险。
procedure:
  1. 校验 JSON schema 合法性。
  2. 清理 boxed 长文本与证明污染。
  3. 修复 final_answer.value 为空等问题。
  4. 单题修复失败时返回失败对象，不中断 batch。
heuristics:
  - 与 Formatter Repair v1 一致：优先提取短答案、保留可审计状态。
  - 严禁 boxed{42} 伪回退。
constraints:
  - final_answer.value 不得为空。
  - boxed 不得包含长 Markdown 或整段证明。
  - 不允许出现 boxed{42} fallback。
fallback:
  - schema 无法修复时返回 success=false 与 error 字段。
final_answer_rules:
  - final_answer.value 必须为短可读答案。
  - boxed 仅在短答案且类型匹配时生成。
trace_notes:
  - 记录修复标记、触发规则、是否影响状态。
