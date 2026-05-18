name: calculation
applies_to: arithmetic, numeric, evaluation, simplification
input_features: 直接计算/求值/化简题，目标为数值或短表达式。
procedure:
  1. 简单算术优先工具计算。
  2. 必要时执行 numeric_check 复核。
  3. 输出最短可验证答案。
heuristics:
  - 对可约分分数与根式做标准化。
  - 保持单位/符号一致。
constraints:
  - final_answer.value 必须简短。
  - 避免默认或伪造 boxed{42} fallback。
fallback:
  - 计算失败时返回失败原因与最接近中间结果，不崩溃。
final_answer_rules:
  - value 为单个数值或短表达式。
  - boxed 可选，不含长文本。
trace_notes:
  - 记录 numeric_check 与关键中间值。
