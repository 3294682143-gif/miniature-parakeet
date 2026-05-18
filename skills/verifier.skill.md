name: verifier
applies_to: verification, post_check
input_features: 需要对候选答案进行正确性验证。
procedure:
  1. 数值题使用 numeric_check。
  2. 表达式题使用 symbolic_check。
  3. 方程题使用 substitution。
  4. 证明题使用 logic_review。
heuristics:
  - 异常必须捕获并降级，不得崩溃。
  - 不应裸信 majority vote，必须结合可验证证据。
constraints:
  - verifier 失败不能导致整批任务中断。
fallback:
  - 工具不可用时记录原因并返回 passed=false/uncertain。
final_answer_rules:
  - 不改写主答案，仅补充 verification 字段。
trace_notes:
  - 记录 method、passed、notes 与异常信息。
